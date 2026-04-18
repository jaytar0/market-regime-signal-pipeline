from dotenv import load_dotenv
import polars as pl
import pandas as pd
import numpy as np
import os
import mlflow, mlflow.sklearn
from mlflow.tracking import MlflowClient
from sklearn.metrics import accuracy_score, roc_auc_score, confusion_matrix
from datetime import date
import scipy.stats as stats
import matplotlib.pyplot as plt
from statsmodels.stats.outliers_influence import variance_inflation_factor
from sklearn.preprocessing import StandardScaler, RobustScaler
import pickle
import json
from sklearn.mixture import GaussianMixture
from hmmlearn.hmm import GaussianHMM
import plotly.graph_objects as go
import warnings
import logging
from itertools import product
warnings.filterwarnings('ignore', category=pd.errors.SettingWithCopyWarning)
logging.getLogger('mlflow').setLevel(logging.ERROR)
warnings.filterwarnings('ignore', category=UserWarning)

load_dotenv()


# --- Initial Read of Gold Layer information and initial data cleaning
DB_URL =  f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@localhost:5432/{os.getenv('POSTGRES_DB')}"
GOLD_TABLE=os.getenv("GOLD_TABLE")

# select from table
gold_df = pl.read_database_uri(
    query=f"SELECT g.* FROM {GOLD_TABLE} as g",
    uri=DB_URL
)
# drop all na rows
df = gold_df.to_pandas().dropna()

# drop metadata and ohlcv columns
drop_default_cols= [
    'symbol', 'featured_at', 'open', 'high', 'low', 'close', 'volume', 'trade_count', 'vwap'  
]

df = df.drop(columns=drop_default_cols)


# --- Feature Selection and Culling ---

# correlation culling method
def correlation_cull(df, features, threshold=0.85):
    c_matrix = df[features].corr().abs()
    c_u = c_matrix.where(
        np.triu(np.ones(c_matrix.shape), k=1).astype(bool)
    )

    drop_logic = [c for c in c_u.columns if any(c_u[c] > threshold)]

    return [f for f in features if f not in drop_logic], drop_logic

corr_select, corr_discard = correlation_cull(df, df.columns, 0.85)

def vif_cull(df, features, threshold=10):
    remaining = features.copy()
    
    while True:
        X = df[remaining].dropna()
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        vif_data = pd.DataFrame({
            'feature': remaining,
            'VIF': [variance_inflation_factor(X_scaled, i) 
                    for i in range(X_scaled.shape[1])]
        }).sort_values('VIF', ascending=False)
        
        max_vif = vif_data.iloc[0]['VIF']
        max_feat = vif_data.iloc[0]['feature']
        
        if max_vif > threshold:
            print(f"Dropping '{max_feat}' with VIF = {max_vif:.2f}")
            remaining.remove(max_feat)
        else:
            break
    
    print(f"\nFinal VIF table:\n{vif_data}")
    return remaining

corr_select.remove("timestamp")
feature_cols_final = vif_cull(df, corr_select, threshold=10)

# getting final feature columns
feature_cols_final_no_ts = [col for col in feature_cols_final if col != 'timestamp']

# perform 80-20 split to train and test data
split_idx = int(len(df) * 0.8)

train_df = df.iloc[:split_idx]
test_df = df.iloc[split_idx:]

X_train = train_df[feature_cols_final_no_ts].values
X_test = test_df[feature_cols_final_no_ts].values

# apply scaling
scaler = RobustScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# --- API usage consideration ---

# dump scaler to pkl for api usage later
os.makedirs("api", exist_ok=True)
with open("api/scaler.pkl", "wb") as f:
    pickle.dump(scaler, f)


# dump columns to json for api usage later
feature_cols_clean = [col for col in feature_cols_final_no_ts 
                      if col != 'hmm_n3_full_iter100_seed420_regime']

with open("api/feature_cols.json", "w") as f:
    json.dump(feature_cols_clean, f)


# --- MLFLOW START ---

mlflow.set_tracking_uri("http://localhost:5000")
exp = mlflow.set_experiment("regime_spy_qqq")


# Plots price action with background color overlays for market regimes.
def plot_regime_overlay(df, label_col, price_col='close', model_name="HMM", crisis_regime=1, bull_regime=2, trans_regime=0):

    fig = go.Figure()

    # 1. Add the Price Line
    fig.add_trace(go.Scatter(
        x=df['timestamp'],
        y=df[price_col],
        mode='lines',
        name=f'{price_col.upper()} Price',
        line=dict(color='black', width=1.5)
    ))

    regime_colors = {
        crisis_regime: 'rgba(255, 50, 50, 0.3)',
        bull_regime:   'rgba(50, 205, 50, 0.3)',
        trans_regime:  'rgba(255, 165, 0, 0.3)'
    }

    regime_names = {
        crisis_regime: 'Crisis',
        bull_regime:   'Bull/Calm',
        trans_regime:  'Transitional'
    }

    # We iterate and find contiguous blocks of the same regime
    current_regime = df[label_col].iloc[0]
    start_idx = 0

    for i in range(1, len(df)):
        # If regime changes OR it's the last row
        if df[label_col].iloc[i] != current_regime or i == len(df) - 1:
            fig.add_vrect(
                x0=df['timestamp'].iloc[start_idx],
                x1=df['timestamp'].iloc[i],
                fillcolor=regime_colors[int(current_regime)],
                layer='below',
                line_width=0
            )
            # Reset for next block
            start_idx = i
            current_regime = df[label_col].iloc[i]

    # Add Legend Entries (using dummy traces)
    for regime, name in regime_names.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='markers',
            marker=dict(size=12, color=regime_colors[regime].replace('0.3', '0.8'), symbol='square'),
            name=name
        ))

    fig.update_layout(
        title=f'Price Action with {model_name} Regime Overlay',
        xaxis_title='Date',
        yaxis_title='Price',
        template='plotly_white',
        height=600,
        width=1200,
        showlegend=True
    )
    
    return fig

# Performs all logging and related metrics for hmm regime detection
def log_regime_model(model, model_name, X_train, X_test, train_df, test_df, base_full_df, model_type="HMM"):
   
    with mlflow.start_run(run_name=model_name):
        
        # predict and autodetect crisis
        regime_col = f"{model_name.lower()}_regime"
        train_df[regime_col] = model.predict(X_train)

        regime_col = f"{model_type.lower()}_regime"
        train_df = train_df.copy()
        test_df = test_df.copy()
        train_df[regime_col] = model.predict(X_train)
        test_df[regime_col] = model.predict(X_test)
        full_df = pd.concat([train_df, test_df]).sort_values('timestamp').reset_index(drop=True)
        full_df = full_df.merge(base_full_df[['timestamp', 'close']], on='timestamp', how='left')
        full_df[regime_col] = full_df[regime_col].astype(int)

        # parameters
        mlflow.log_param("model_type", model_name)
        mlflow.log_param("n_components", model.n_components)
        mlflow.log_param("covariance_type", model.covariance_type)

        # BIC and Log Likelihood calculations
        if model_name == "HMM":

            n_samples, n_features = X_train.shape
            n_states = model.n_components
            cov_type = model.covariance_type
            
            if cov_type == 'full':
                cov_params = n_states * n_features * (n_features + 1) / 2
            elif cov_type == 'tied':
                cov_params = n_features * (n_features + 1) / 2
            elif cov_type == 'diag':
                cov_params = n_states * n_features
            elif cov_type == 'spherical':
                cov_params = n_states

            k = (n_states**2 - n_states) + (n_states - 1) + (n_states * n_features) + cov_params
            log_lik = model.score(X_train)
            bic = -2 * log_lik + k * np.log(n_samples)

        else:
            log_lik = model.score(X_train) * len(X_train)
            bic = model.bic(X_train)

        mlflow.log_metric("log_likelihood", log_lik)
        mlflow.log_metric("bic", bic)

        # stability calculations
        labels = train_df[regime_col].values
        transitions = (labels[1:] != labels[:-1]).sum()
        avg_run = len(labels) / transitions if transitions > 0 else len(labels)

        mlflow.log_metric("n_transitions", transitions)
        mlflow.log_metric("avg_run_length_days", avg_run)

        # sharpe calculated per regime
        stats = train_df.groupby(regime_col)['log_return'].agg(['mean', 'std'])
        sharpes = (stats['mean'] / stats['std']) * np.sqrt(252)
        for regime_id, sharpe_val in sharpes.items():
            mlflow.log_metric(f"sharpe_regime_{regime_id}", round(sharpe_val, 3))

        crisis_regime = stats['std'].idxmax()                                              # highest vol = crisis
        bull_regime = (stats['mean'] / stats['std']).idxmax()                              # highest sharpe = bull
        trans_regime = [r for r in stats.index if r not in [crisis_regime, bull_regime]][0]  # remainder = transitional

        # Max and average drawdown calculations
        strat_ret = np.where(train_df[regime_col] == crisis_regime, 0, train_df['log_return'])
        bench_cum = train_df['log_return'].cumsum().apply(np.exp)
        strat_cum = pd.Series(strat_ret).cumsum().apply(np.exp)

        bench_dd = (bench_cum / bench_cum.cummax()) - 1
        strat_dd = (strat_cum / strat_cum.cummax()) - 1

        bench_mdd = bench_dd.min()
        strat_mdd = strat_dd.min()
        bench_avg_dd = bench_dd[bench_dd < 0].mean()
        strat_avg_dd = strat_dd[strat_dd < 0].mean()

        mlflow.log_metric("benchmark_mdd", bench_mdd)
        mlflow.log_metric("strategy_mdd", strat_mdd)
        mlflow.log_metric("benchmark_avg_drawdown", bench_avg_dd)
        mlflow.log_metric("strategy_avg_drawdown", strat_avg_dd)

        # log all three regime labels
        mlflow.log_param("crisis_regime_label", int(crisis_regime))
        mlflow.log_param("bull_regime_label", int(bull_regime))
        mlflow.log_param("trans_regime_label", int(trans_regime))

        # addition labels statistics
        regime_means = train_df.groupby(regime_col)['log_return'].mean()
        for regime_id, mean_val in regime_means.items():
            mlflow.log_metric(f"mean_return_regime_{regime_id}", round(mean_val, 6))

        # graphing
        if model.n_components == 3:
            fig_hmm = plot_regime_overlay(full_df, 'hmm_regime', model_name="HMM", crisis_regime=crisis_regime, bull_regime=bull_regime, trans_regime=trans_regime)
            mlflow.log_figure(fig_hmm, "regime_overlay_hmm.html")

        # Model Artifacting
        mlflow.sklearn.log_model(model, artifact_path=model_name.lower())

        print(f"[{model_name}] Crisis Regime: {crisis_regime} | BIC: {bic:.2f} | Transitions: {transitions} | Avg Run: {avg_run:.1f}d")


# --- MAIN LOOP FOR GRIDSEARCH ---
# This is currently set to just the best parameter that concluded from the project experiments.

# grid search run

# grid search parameters
# param_grid = {
#     'n_components':    [3, 4],
#     'covariance_type': ['full', 'tied', 'diag'],
#     'n_iter':          [100, 200, 300],
#     'random_state':    [420, 123, 1337, 69, 808]
# }

param_grid = {
    'n_components':    [3],
    'covariance_type': ['full'],
    'n_iter':          [100],
    'random_state':    [420]
}


keys = list(param_grid.keys())
values = list(param_grid.values())

# base full_df with price — built once, regimes get added per run inside the function
price_df = gold_df.to_pandas()[['timestamp', 'close']].dropna()
base_full_df = pd.concat([train_df, test_df]).sort_values('timestamp').reset_index(drop=True)
base_full_df = base_full_df.merge(price_df, on='timestamp', how='left')

for combo in product(*values):
    
    params = dict(zip(keys, combo))
    
    model = GaussianHMM(
        n_components=params['n_components'],
        covariance_type=params['covariance_type'],
        n_iter=params['n_iter'],
        random_state=params['random_state']
    )
    
    try:
        model.fit(X_train_scaled)
    except Exception as e:
        print(f"Failed: {params} | {e}")
        continue

    if not model.monitor_.converged:
        print(f"Did not converge: {params}")
        continue

    with open("api/model.pkl", "wb") as f:
        pickle.dump(model, f)
    print("done")
    
    run_name = f"HMM_n{params['n_components']}_{params['covariance_type']}_iter{params['n_iter']}_seed{params['random_state']}"
    
    log_regime_model(model, run_name, X_train_scaled, X_test_scaled, train_df, test_df, base_full_df.copy())