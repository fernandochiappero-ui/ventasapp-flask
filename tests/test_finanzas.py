import os
import unittest
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models import Usuario, Proveedor, CompraProveedor, PagoCompraProveedor, Egreso, AuditoriaEgreso


class FinanzasTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        with self.app.app_context():
            db.session.add_all([self.usuario("admin", "administrador"), self.usuario("vendedor", "vendedor")])
            db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    @staticmethod
    def usuario(nombre, rol):
        u = Usuario(username=nombre, rol=rol)
        u.set_password("clave")
        return u

    def login(self, username):
        self.client.post("/login", data={"username": username, "password": "clave"})

    def proveedor(self, nombre="Alfa"):
        with self.app.app_context():
            p = Proveedor(nombre=nombre)
            db.session.add(p)
            db.session.commit()
            return p.id

    def crear_compra(self, proveedor_id, total="100", pagado="0", forma="cuenta_corriente", factura="F-1"):
        return self.client.post("/compras/nueva", data={
            "proveedor_id": proveedor_id, "total": total, "pagado": pagado,
            "forma_pago": forma, "fecha": "2026-10-12", "factura": factura,
        }, follow_redirects=True)

    def test_01_vendedor_alta_proveedor(self):
        self.login("vendedor")
        response = self.client.post("/proveedores/nuevo", data={"nombre": "La Huerta"}, follow_redirects=True)
        self.assertIn(b"La Huerta", response.data)

    def test_02_alta_aparece_en_busqueda(self):
        self.login("vendedor")
        self.client.post("/proveedores/nuevo", data={"nombre": "La Huerta"})
        self.assertEqual(self.client.get("/api/proveedores?q=hu").json[0]["nombre"], "La Huerta")

    def test_03_busqueda_parcial_alfabetica_y_sin_duplicar(self):
        self.login("admin")
        for n in ["Beta Sur", "Álamo", "Alfa", "Alfa"]:
            self.client.post("/proveedores/nuevo", data={"nombre": n})
        result = self.client.get("/api/proveedores?q=al").json
        names = [x["nombre"] for x in result]
        self.assertEqual(names, ["Álamo", "Alfa"])

    def test_04_factura_pagada_total(self):
        self.login("vendedor"); pid = self.proveedor()
        self.crear_compra(pid, "80", "80", "efectivo")
        with self.app.app_context():
            c = CompraProveedor.query.one()
            self.assertEqual(c.saldo, Decimal("0.00"))
            self.assertEqual(Egreso.query.filter_by(pago_compra_id=c.pagos[0].id).count(), 1)

    def test_05_factura_parcial(self):
        self.login("vendedor"); self.crear_compra(self.proveedor(), "100", "25", "transferencia")
        with self.app.app_context(): self.assertEqual(CompraProveedor.query.one().saldo, Decimal("75.00"))

    def test_06_factura_en_cuenta_corriente(self):
        self.login("vendedor"); self.crear_compra(self.proveedor(), "100", "0")
        with self.app.app_context(): self.assertEqual(CompraProveedor.query.one().pagos, [])

    def test_07_saldo_baja_con_pago_imputado(self):
        self.login("vendedor"); self.crear_compra(self.proveedor(), "100", "20", "efectivo")
        with self.app.app_context(): c = CompraProveedor.query.one(); cid = c.id
        self.client.post(f"/compras/{cid}/pago", data={"monto": "30", "forma_pago": "efectivo"})
        with self.app.app_context(): self.assertEqual(CompraProveedor.query.one().saldo, Decimal("50.00"))

    def test_08_vendedor_registra_egreso(self):
        self.login("vendedor")
        response = self.client.post("/egresos", data={"monto": "12.50", "concepto": "Flete", "categoria": "gasto", "forma_pago": "efectivo"})
        self.assertEqual(response.status_code, 302)
        with self.app.app_context(): self.assertEqual(Egreso.query.filter_by(concepto="Flete").one().usuario.username, "vendedor")

    def test_09_admin_ve_egresos_de_ambos(self):
        self.login("vendedor"); self.client.post("/egresos", data={"monto": "10", "concepto": "Vendedor", "categoria": "retiro", "forma_pago": "efectivo"})
        self.client.get("/logout"); self.login("admin"); self.client.post("/egresos", data={"monto": "20", "concepto": "Admin", "categoria": "gasto", "forma_pago": "efectivo"})
        page = self.client.get("/egresos")
        self.assertIn(b"Vendedor", page.data); self.assertIn(b"Admin", page.data)

    def test_10_admin_filtra_vendedor(self):
        self.login("vendedor"); self.client.post("/egresos", data={"monto": "10", "concepto": "Solo vendedor", "categoria": "retiro", "forma_pago": "efectivo"})
        self.client.get("/logout"); self.login("admin")
        self.assertIn(b"Solo vendedor", self.client.get("/egresos?usuario_id=2").data)

    def test_11_pdf_filtra_y_se_descarga(self):
        self.login("vendedor"); self.client.post("/egresos", data={"monto": "12", "concepto": "Filtro PDF", "categoria": "gasto", "forma_pago": "efectivo"})
        self.client.get("/logout"); self.login("admin")
        response = self.client.get("/egresos/reporte.pdf?desde=2026-10-01&hasta=2026-10-31")
        self.assertEqual(response.mimetype, "application/pdf"); self.assertEqual(response.status_code, 200)

    def test_12_modificar_actualiza_total(self):
        self.login("vendedor"); self.client.post("/egresos", data={"monto": "12", "concepto": "Cambio", "categoria": "gasto", "forma_pago": "efectivo"})
        self.client.get("/logout"); self.login("admin")
        with self.app.app_context(): eid = Egreso.query.one().id
        self.client.post(f"/egresos/{eid}/editar", data={"fecha": "2026-10-12", "monto": "33", "concepto": "Cambio", "categoria": "gasto", "forma_pago": "efectivo"})
        with self.app.app_context(): self.assertEqual(Egreso.query.one().monto, Decimal("33.00"))

    def test_13_auditoria_guarda_antes_y_despues(self):
        self.test_12_modificar_actualiza_total()
        with self.app.app_context():
            a = AuditoriaEgreso.query.one()
            self.assertEqual(a.anteriores["monto"], "12.00")
            self.assertEqual(a.nuevos["monto"], "33.00")

    def test_14_vendedor_no_modifica_egresos_ni_proveedores(self):
        pid = self.proveedor(); self.login("vendedor")
        self.assertEqual(self.client.post(f"/proveedores/{pid}/baja").status_code, 302)
        self.client.post("/egresos", data={"monto": "12", "concepto": "E", "categoria": "gasto", "forma_pago": "efectivo"})
        with self.app.app_context(): eid = Egreso.query.one().id
        self.assertNotEqual(self.client.get(f"/egresos/{eid}/editar").status_code, 200)

    def test_15_rutas_anteriores_y_nuevos_modulos_siguen_respondiendo(self):
        self.login("admin")
        self.assertEqual(self.client.get("/retiros").status_code, 302)
        self.assertEqual(self.client.get("/proveedores").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_16_pago_de_factura_se_cuenta_una_vez(self):
        self.login("vendedor"); self.crear_compra(self.proveedor(), "100", "30", "efectivo")
        with self.app.app_context():
            self.assertEqual(Egreso.query.filter_by(categoria="pago_proveedor").count(), 1)
            self.assertEqual(PagoCompraProveedor.query.count(), 1)


if __name__ == "__main__":
    unittest.main()
