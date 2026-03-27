-- DROP SCHEMA bronze CASCADE;
-- DROP SCHEMA silver CASCADE;

SELECT 
	symbol, "timestamp", "open", high, low, "close", 
	volume, trade_count, vwap, log_return, hl_range,
	volume_ratio, rolling_vol, rolling_sharpe, featured_at
FROM 
	gold.hw5;



select * from silver.regime


select timestamp from gold.regime
select max(timestamp) from gold.regime

DELETE FROM bronze.regime 
WHERE timestamp = '2026-03-24 04:00:00+00' 
AND symbol IN ('QQQ', 'SPY');