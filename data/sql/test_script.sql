-- DROP SCHEMA bronze CASCADE;
-- DROP SCHEMA silver CASCADE;

SELECT 
	symbol, "timestamp", "open", high, low, "close", 
	volume, trade_count, vwap, log_return, hl_range,
	volume_ratio, rolling_vol, rolling_sharpe, featured_at
FROM 
	gold.hw5;