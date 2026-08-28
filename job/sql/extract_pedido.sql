-- Extract query for bronze.pedido (order headers).
-- Full snapshot each run: see extract_cliente.sql for rationale.
SELECT
    id_pedido,
    dui_cliente,
    fecha_pedido,
    estado
FROM bronze.pedido;
