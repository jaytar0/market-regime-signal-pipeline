SELECT symbol, "timestamp", "open", high, low, "close", volume, trade_count, vwap
FROM bronze.hw5;

select
	symbol,
	count(*)
from
bronze.hw5
group by symbol

select
 max(timestamp)
 from
 bronze.hw5
 
 
-- DROP SCHEMA bronze CASCADE;