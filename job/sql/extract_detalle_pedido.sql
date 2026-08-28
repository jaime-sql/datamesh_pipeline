-- Extract query for bronze.detalle_pedido (order line items).
-- Full snapshot each run: see extract_cliente.sql for rationale.
SELECT
    id_detalle,
    id_pedido,
    id_producto,
    cantidad,
    precio_unitario_historico
FROM bronze.detalle_pedido;
