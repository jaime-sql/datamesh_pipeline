-- Extract query for bronze.cliente (customers).
-- Full snapshot each run: source has no updated_at/change-tracking column,
-- and the table is tiny, so a full read + BigQuery WRITE_TRUNCATE is simplest.
SELECT
    dui_cliente,
    nombre,
    telefono,
    direccion,
    id_municipio
FROM bronze.cliente;
