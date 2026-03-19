SELECT *
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
-- DROP SCHEMA silver CASCADE;

select * from silver.quarantine