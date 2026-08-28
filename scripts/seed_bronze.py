"""
Idempotent seed script for the Neon `bronze` schema.

Existing data (2 clientes, 4 detalle_pedido rows referencing orders 1001/1002,
no orders header table) is kept as-is. This script:

  1. Creates bronze.pedido (order header table) if it doesn't exist yet.
  2. Backfills pedido rows for the pre-existing orders 1001/1002 so they link
     to the two pre-existing clientes.
  3. Adds a handful of new clientes, pedidos, and detalle_pedido rows so the
     dataset is large enough to meaningfully demo an incremental copy job.

Safe to re-run: every insert is guarded by a NOT EXISTS check keyed on a
natural identifier, so running this twice will not create duplicates.

Usage:
    python scripts/seed_bronze.py
"""

import os
from datetime import date

from dotenv import load_dotenv
import psycopg2

load_dotenv()

CREATE_PEDIDO_TABLE = """
    CREATE TABLE IF NOT EXISTS bronze.pedido (
        id_pedido    INTEGER,
        dui_cliente  VARCHAR,
        fecha_pedido DATE,
        estado       VARCHAR
    );
"""

INSERT_PEDIDO = """
    INSERT INTO bronze.pedido (id_pedido, dui_cliente, fecha_pedido, estado)
    SELECT %(id_pedido)s, %(dui_cliente)s, %(fecha_pedido)s, %(estado)s
    WHERE NOT EXISTS (
        SELECT 1 FROM bronze.pedido WHERE id_pedido = %(id_pedido)s
    );
"""

INSERT_CLIENTE = """
    INSERT INTO bronze.cliente (dui_cliente, nombre, telefono, direccion, id_municipio)
    SELECT %(dui_cliente)s, %(nombre)s, %(telefono)s, %(direccion)s, %(id_municipio)s
    WHERE NOT EXISTS (
        SELECT 1 FROM bronze.cliente WHERE dui_cliente = %(dui_cliente)s
    );
"""

INSERT_DETALLE = """
    INSERT INTO bronze.detalle_pedido (id_detalle, id_pedido, id_producto, cantidad, precio_unitario_historico)
    SELECT %(id_detalle)s, %(id_pedido)s, %(id_producto)s, %(cantidad)s, %(precio)s
    WHERE NOT EXISTS (
        SELECT 1 FROM bronze.detalle_pedido WHERE id_detalle = %(id_detalle)s
    );
"""

# Backfill order headers for the two pre-existing orders (1001/1002),
# linking to the two pre-existing clientes.
BACKFILL_PEDIDOS = [
    dict(id_pedido=1001, dui_cliente="05123456-7", fecha_pedido=date(2026, 6, 3), estado="completado"),
    dict(id_pedido=1002, dui_cliente="06112233-4", fecha_pedido=date(2026, 6, 10), estado="completado"),
]

NEW_CLIENTES = [
    dict(dui_cliente="07234567-8", nombre="Ana Lucía Reyes", telefono="7456-7890", direccion="Col. Miramonte, Calle Los Pinos #8", id_municipio=1),
    dict(dui_cliente="08345678-9", nombre="Carlos Alberto Mejía", telefono="7567-8901", direccion="Res. San Antonio, Pje. 5 #22", id_municipio=3),
    dict(dui_cliente="09456789-0", nombre="Fátima Beatriz López", telefono="7678-9012", direccion="Barrio San Jacinto, 4a Calle Ote. #17", id_municipio=1),
    dict(dui_cliente="10567890-1", nombre="Ricardo Ernesto Flores", telefono="7789-0123", direccion="Col. Santa Lucía, Av. Central #3", id_municipio=2),
    dict(dui_cliente="11678901-2", nombre="Gabriela Alejandra Cruz", telefono="7890-1235", direccion="Urb. El Rosario, Pje. 2 #9", id_municipio=4),
]

NEW_PEDIDOS = [
    dict(id_pedido=1003, dui_cliente="07234567-8", fecha_pedido=date(2026, 7, 2), estado="completado"),
    dict(id_pedido=1004, dui_cliente="08345678-9", fecha_pedido=date(2026, 7, 15), estado="pendiente"),
    dict(id_pedido=1005, dui_cliente="09456789-0", fecha_pedido=date(2026, 7, 20), estado="completado"),
    dict(id_pedido=1006, dui_cliente="10567890-1", fecha_pedido=date(2026, 8, 1), estado="cancelado"),
    dict(id_pedido=1007, dui_cliente="11678901-2", fecha_pedido=date(2026, 8, 12), estado="completado"),
    dict(id_pedido=1008, dui_cliente="07234567-8", fecha_pedido=date(2026, 8, 20), estado="pendiente"),
]

NEW_DETALLES = [
    dict(id_detalle=5, id_pedido=1003, id_producto="PROD-03", cantidad=3, precio=3.50),
    dict(id_detalle=6, id_pedido=1003, id_producto="PROD-01", cantidad=1, precio=1.25),
    dict(id_detalle=7, id_pedido=1004, id_producto="PROD-08", cantidad=5, precio=2.00),
    dict(id_detalle=8, id_pedido=1005, id_producto="PROD-12", cantidad=2, precio=2.50),
    dict(id_detalle=9, id_pedido=1005, id_producto="PROD-15", cantidad=4, precio=1.75),
    dict(id_detalle=10, id_pedido=1006, id_producto="PROD-01", cantidad=8, precio=1.25),
    dict(id_detalle=11, id_pedido=1007, id_producto="PROD-03", cantidad=2, precio=3.50),
    dict(id_detalle=12, id_pedido=1007, id_producto="PROD-08", cantidad=1, precio=2.00),
    dict(id_detalle=13, id_pedido=1008, id_producto="PROD-12", cantidad=3, precio=2.50),
]


def main() -> None:
    conn = psycopg2.connect(os.environ["NEON_DATABASE_URL"], connect_timeout=10)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_PEDIDO_TABLE)

            for row in BACKFILL_PEDIDOS:
                cur.execute(INSERT_PEDIDO, row)

            for row in NEW_CLIENTES:
                cur.execute(INSERT_CLIENTE, row)

            for row in NEW_PEDIDOS:
                cur.execute(INSERT_PEDIDO, row)

            for row in NEW_DETALLES:
                cur.execute(INSERT_DETALLE, row)

        conn.commit()
        print("Seed complete.")

        with conn.cursor() as cur:
            for table in ("cliente", "pedido", "detalle_pedido"):
                cur.execute(f"SELECT COUNT(*) FROM bronze.{table};")
                print(f"  bronze.{table}: {cur.fetchone()[0]} rows")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
