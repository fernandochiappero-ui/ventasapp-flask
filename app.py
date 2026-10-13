# app.py
#
# Este es el "corazón" de la aplicación web. Un archivo Flask típico
# hace tres cosas:
#   1) Configura la app (base de datos, clave secreta, login).
#   2) Define "rutas": qué función de Python se ejecuta cuando el
#      navegador pide una URL determinada (ej: GET /clientes).
#   3) Cada función arma los datos y le pide a una plantilla HTML
#      (carpeta templates/) que los muestre.
#
# Para levantar el servidor: python app.py
# Luego abrir http://127.0.0.1:5000 en el navegador (PC o celular,
# ver README.md para cómo entrar desde el celular).

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from zoneinfo import ZoneInfo
import os
import unicodedata

from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, send_file
from fpdf import FPDF
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from functools import wraps
from sqlalchemy import inspect, or_, text
from extensions import db, login_manager
from models import (
    Usuario, Cliente, Venta, MovimientoCC, ProductoAlmacen, ProductoVerduleria,
    Proveedor, PagoProveedor, RetiroVendedor, CompraProveedor,
    PagoCompraProveedor, Egreso, AuditoriaEgreso,
)

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")
def hoy_argentina(): return datetime.now(ZONA_HORARIA).date()

def normalizar(texto):
    """Minúsculas y sin tildes: 'Orégano' -> 'oregano'."""
    texto = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return sin_tildes.casefold()

def resolver_precio(costo, porcentaje, precio_texto):
    """Devuelve (porcentaje, precio_venta, error)."""
    cien = Decimal("100")
    centavo = Decimal("0.01")
    calculado = (costo * (Decimal("1") + porcentaje / cien)).quantize(
        centavo, rounding=ROUND_HALF_UP
    )
    precio_texto = (precio_texto or "").strip().replace(",", ".")
    if not precio_texto:
        return porcentaje, calculado, None
    try:
        precio = Decimal(precio_texto)
        if not precio.is_finite() or precio < 0:
            raise InvalidOperation
    except InvalidOperation:
        return porcentaje, calculado, "El precio de venta debe ser un número igual o mayor a cero."
    precio = precio.quantize(centavo, rounding=ROUND_HALF_UP)
    if costo <= 0 or precio == calculado:
        # sin costo no se puede calcular el %; o no tocó el precio
        return porcentaje, precio, None
    nuevo = ((precio / costo - Decimal("1")) * cien).quantize(
        centavo, rounding=ROUND_HALF_UP
    )
    if nuevo < 0:
        return porcentaje, precio, "El precio de venta no puede ser menor al costo."
    if nuevo > 9999:
        return porcentaje, precio, "El precio de venta es demasiado alto para ese costo."
    return nuevo, precio, None

FORMAS_PAGO = {
    "efectivo": "Efectivo",
    "cuenta_corriente": "Cta. Cte.",
    "tarjeta_qr": "Tarjeta/QR",
    "transferencia": "Transferencia",
}

def totales_por_forma(ventas):
    """Suma el monto de las ventas agrupado por forma de pago."""
    totales = {forma: 0 for forma in FORMAS_PAGO}
    for v in ventas:
        if v.forma_pago in totales:
            totales[v.forma_pago] += v.monto
    return {forma: round(monto, 2) for forma, monto in totales.items()}

TIPOS_EGRESO = {
    "pago_total": "Pago total",
    "pago_parcial": "Pago parcial",
    "cuenta_corriente": "A cuenta corriente",
}

def create_app():
    app = Flask(__name__)
    app.jinja_env.globals["FORMAS_PAGO"] = FORMAS_PAGO
    app.jinja_env.globals["TIPOS_EGRESO"] = TIPOS_EGRESO
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "cambia-esta-clave-por-una-propia"
    )

    # Le decimos a SQLAlchemy que use un archivo SQLite (una base de
    # datos liviana que es un solo archivo, ideal para un proyecto chico).
    database_url = os.environ.get("DATABASE_URL", "sqlite:///base_datos.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        db.create_all()
        columnas_usuario = {
            columna["name"] for columna in inspect(db.engine).get_columns("usuarios")
        }
        if "rol" not in columnas_usuario:
            db.session.execute(
                text(
                    "ALTER TABLE usuarios ADD COLUMN rol "
                    "VARCHAR(20) NOT NULL DEFAULT 'administrador'"
                )
            )
            db.session.commit()
        columnas_producto = {
            columna["name"]
            for columna in inspect(db.engine).get_columns("productos_almacen")
        }
        if "porcentaje_ganancia" not in columnas_producto:
            db.session.execute(
                text(
                    "ALTER TABLE productos_almacen ADD COLUMN "
                    "porcentaje_ganancia NUMERIC(6, 2) NOT NULL DEFAULT 0"
                )
            )
            db.session.commit()
        columnas_ventas = {
            columna["name"] for columna in inspect(db.engine).get_columns("ventas")
        }
        if "usuario_id" not in columnas_ventas:
            db.session.execute(
                text("ALTER TABLE ventas ADD COLUMN usuario_id INTEGER")
            )
            db.session.commit()
        columnas_movimientos = {
            columna["name"]
            for columna in inspect(db.engine).get_columns("movimientos_cc")
        }
        if "usuario_id" not in columnas_movimientos:
            db.session.execute(
                text("ALTER TABLE movimientos_cc ADD COLUMN usuario_id INTEGER")
            )
            db.session.commit()
        columnas_proveedor = {
            columna["name"] for columna in inspect(db.engine).get_columns("proveedores")
        }
        for nombre, definicion in {
            "cuit": "VARCHAR(20)",
            "direccion": "VARCHAR(200)",
            "email": "VARCHAR(150)",
            "observaciones": "VARCHAR(500)",
        }.items():
            if nombre not in columnas_proveedor:
                db.session.execute(text(f"ALTER TABLE proveedores ADD COLUMN {nombre} {definicion}"))
        columnas_egreso = {c["name"] for c in inspect(db.engine).get_columns("egresos")}
        for nombre in ("legacy_retiro_id", "legacy_pago_proveedor_id", "pago_compra_id"):
            if nombre not in columnas_egreso:
                db.session.execute(text(f"ALTER TABLE egresos ADD COLUMN {nombre} INTEGER"))
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_egresos_legacy_retiro ON egresos (legacy_retiro_id)"))
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_egresos_legacy_pago ON egresos (legacy_pago_proveedor_id)"))
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_egresos_pago_compra ON egresos (pago_compra_id)"))
        # Copia histórica idempotente: los registros originales permanecen intactos.
        retiros_legado = RetiroVendedor.query.all()
        for retiro in retiros_legado:
            if not Egreso.query.filter_by(legacy_retiro_id=retiro.id).first():
                db.session.add(Egreso(
                    legacy_retiro_id=retiro.id, usuario_id=retiro.usuario_id,
                    fecha=retiro.creado or datetime.combine(retiro.fecha, datetime.min.time()),
                    monto=Decimal(str(retiro.monto)), concepto=retiro.descripcion or "Retiro del vendedor",
                    categoria="retiro", forma_pago="efectivo",
                ))
        pagos_legado = PagoProveedor.query.filter(PagoProveedor.tipo != "cuenta_corriente").all()
        for pago_legado in pagos_legado:
            if not Egreso.query.filter_by(legacy_pago_proveedor_id=pago_legado.id).first():
                db.session.add(Egreso(
                    legacy_pago_proveedor_id=pago_legado.id, usuario_id=pago_legado.usuario_id,
                    fecha=pago_legado.creado or datetime.combine(pago_legado.fecha, datetime.min.time()),
                    monto=Decimal(str(pago_legado.monto)),
                    concepto=f"Pago a proveedor: {pago_legado.proveedor.nombre}",
                    categoria="pago_proveedor", forma_pago="otro",
                    observaciones=pago_legado.descripcion,
                ))
        db.session.commit()
    login_manager.init_app(app)
    login_manager.login_view = "login"  # a dónde redirigir si no está logueado
    login_manager.login_message = "Iniciá sesión para continuar."

    def administrador_requerido(funcion):
        @wraps(funcion)
        @login_required
        def protegida(*args, **kwargs):
            if not current_user.es_administrador:
                flash("No tenés permiso para acceder a esa pantalla.", "error")
                return redirect(url_for("nueva_venta"))
            return funcion(*args, **kwargs)

        return protegida

    @login_manager.user_loader
    def load_user(user_id):
        # Flask-Login llama a esta función en cada request para saber
        # quién es el usuario logueado, a partir del id guardado en la cookie.
        return db.session.get(Usuario, int(user_id))

    def decimal_formulario(nombre):
        texto = (request.form.get(nombre) or "").strip().replace(",", ".")
        try:
            valor = Decimal(texto)
            if not valor.is_finite():
                raise InvalidOperation
            return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return None

    @app.route("/proveedores")
    @login_required
    def listar_proveedores():
        q = request.args.get("q", "").strip()
        proveedores = Proveedor.query.order_by(Proveedor.nombre).all()
        if q:
            clave = normalizar(q)
            proveedores = [p for p in proveedores if clave in normalizar(p.nombre)]
        return render_template("proveedores/index.html", proveedores=proveedores, q=q)

    @app.route("/proveedores/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_proveedor():
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            if not nombre:
                flash("El nombre del proveedor es obligatorio.", "error")
            elif any(normalizar(p.nombre) == normalizar(nombre) for p in Proveedor.query.all()):
                flash("Ya existe un proveedor con ese nombre.", "error")
            else:
                proveedor = Proveedor(
                    nombre=nombre, cuit=request.form.get("cuit", "").strip() or None,
                    telefono=request.form.get("telefono", "").strip() or None,
                    direccion=request.form.get("direccion", "").strip() or None,
                    email=request.form.get("email", "").strip() or None,
                    observaciones=request.form.get("observaciones", "").strip() or None,
                )
                db.session.add(proveedor)
                db.session.commit()
                flash("Proveedor agregado.", "success")
                return redirect(url_for("listar_proveedores"))
        return render_template("proveedores/form.html", proveedor=None)

    @app.route("/proveedores/<int:proveedor_id>/editar", methods=["GET", "POST"])
    @administrador_requerido
    def modificar_proveedor(proveedor_id):
        proveedor = db.get_or_404(Proveedor, proveedor_id)
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            otros = Proveedor.query.filter(Proveedor.id != proveedor.id).all()
            if not nombre:
                flash("El nombre es obligatorio.", "error")
            elif any(normalizar(p.nombre) == normalizar(nombre) for p in otros):
                flash("Ya existe otro proveedor con ese nombre.", "error")
            else:
                proveedor.nombre = nombre
                proveedor.cuit = request.form.get("cuit", "").strip() or None
                proveedor.telefono = request.form.get("telefono", "").strip() or None
                proveedor.direccion = request.form.get("direccion", "").strip() or None
                proveedor.email = request.form.get("email", "").strip() or None
                proveedor.observaciones = request.form.get("observaciones", "").strip() or None
                db.session.commit()
                flash("Proveedor actualizado.", "success")
                return redirect(url_for("listar_proveedores"))
        return render_template("proveedores/form.html", proveedor=proveedor)

    @app.route("/proveedores/<int:proveedor_id>/baja", methods=["POST"])
    @administrador_requerido
    def desactivar_proveedor(proveedor_id):
        proveedor = db.get_or_404(Proveedor, proveedor_id)
        proveedor.activo = False
        db.session.commit()
        flash("Proveedor desactivado; se conserva su historial.", "success")
        return redirect(url_for("listar_proveedores"))

    @app.route("/proveedores/<int:proveedor_id>/eliminar", methods=["POST"])
    @administrador_requerido
    def eliminar_proveedor(proveedor_id):
        return eliminar_proveedor_registros(proveedor_id)

    def eliminar_proveedor_registros(proveedor_id):
        proveedor = db.get_or_404(Proveedor, proveedor_id)
        compras = CompraProveedor.query.filter_by(proveedor_id=proveedor.id).all()
        compra_ids = [compra.id for compra in compras]
        pago_compra_ids = [
            pago.id for pago in PagoCompraProveedor.query.filter(
                PagoCompraProveedor.compra_id.in_(compra_ids)
            ).all()
        ] if compra_ids else []
        pagos_legado = PagoProveedor.query.filter_by(proveedor_id=proveedor.id).all()
        pago_legado_ids = [pago.id for pago in pagos_legado]

        filtros_egreso = []
        if pago_compra_ids:
            filtros_egreso.append(Egreso.pago_compra_id.in_(pago_compra_ids))
        if pago_legado_ids:
            filtros_egreso.append(Egreso.legacy_pago_proveedor_id.in_(pago_legado_ids))
        egreso_ids = [r[0] for r in Egreso.query.with_entities(Egreso.id).filter(
            or_(*filtros_egreso)
        ).all()] if filtros_egreso else []
        if egreso_ids:
            AuditoriaEgreso.query.filter(
                AuditoriaEgreso.egreso_id.in_(egreso_ids)
            ).delete(synchronize_session=False)
            Egreso.query.filter(Egreso.id.in_(egreso_ids)).delete(
                synchronize_session=False
            )
        if pago_compra_ids:
            PagoCompraProveedor.query.filter(
                PagoCompraProveedor.id.in_(pago_compra_ids)
            ).delete(synchronize_session=False)
        if compra_ids:
            CompraProveedor.query.filter(
                CompraProveedor.id.in_(compra_ids)
            ).delete(synchronize_session=False)
        if pago_legado_ids:
            PagoProveedor.query.filter(
                PagoProveedor.id.in_(pago_legado_ids)
            ).delete(synchronize_session=False)
        nombre = proveedor.nombre
        Proveedor.query.filter_by(id=proveedor.id).delete(synchronize_session=False)
        db.session.commit()
        flash(f"Proveedor '{nombre}' y su historial eliminados.", "success")
        return redirect(url_for("listar_proveedores"))

    @app.route("/api/proveedores", methods=["GET", "POST"])
    @login_required
    def buscar_proveedores():
        if request.method == "POST":
            datos = request.get_json(silent=True) or {}
            nombre = str(datos.get("nombre", "")).strip()[:150]
            if not nombre:
                return jsonify({"error": "El nombre del proveedor es obligatorio."}), 400
            if any(normalizar(p.nombre) == normalizar(nombre) for p in Proveedor.query.all()):
                return jsonify({"error": "Ya existe un proveedor con ese nombre."}), 409
            proveedor = Proveedor(nombre=nombre)
            db.session.add(proveedor)
            db.session.commit()
            return jsonify({"id": proveedor.id, "nombre": proveedor.nombre}), 201
        q = normalizar(request.args.get("q", "").strip())
        lista = Proveedor.query.filter_by(activo=True).order_by(Proveedor.nombre).all()
        vistos, resultados = set(), []
        for proveedor in sorted(lista, key=lambda p: normalizar(p.nombre)):
            clave = normalizar(proveedor.nombre)
            if q in clave and clave not in vistos:
                vistos.add(clave)
                resultados.append({"id": proveedor.id, "nombre": proveedor.nombre})
            if len(resultados) == 20:
                break
        return jsonify(resultados)

    @app.route("/compras/nueva", methods=["GET", "POST"])
    @login_required
    def nueva_compra_proveedor():
        if request.method == "POST":
            proveedor = db.session.get(Proveedor, request.form.get("proveedor_id", type=int))
            total = decimal_formulario("total")
            pagado = decimal_formulario("pagado") or Decimal("0.00")
            forma = request.form.get("forma_pago", "")
            forma_pago_real = request.form.get("forma_pago_inicial", "") or ("efectivo" if forma == "cuenta_corriente" else forma)
            fecha_texto = request.form.get("fecha", "")
            factura = request.form.get("factura", "").strip() or None
            try:
                fecha = date.fromisoformat(fecha_texto) if fecha_texto else hoy_argentina()
            except ValueError:
                fecha = None
            formas = {"efectivo", "transferencia", "otro", "cuenta_corriente"}
            if not proveedor or not proveedor.activo:
                flash("Elegí un proveedor activo.", "error")
            elif total is None or total <= 0:
                flash("El total debe ser un importe mayor a cero.", "error")
            elif pagado < 0 or pagado > total:
                flash("El pago inicial debe estar entre cero y el total de la factura.", "error")
            elif forma not in formas:
                flash("Elegí una forma de pago válida.", "error")
            elif pagado > 0 and forma_pago_real not in {"efectivo", "transferencia", "otro"}:
                flash("Elegí cómo se pagó el importe inicial.", "error")
            elif fecha is None:
                flash("La fecha de compra no es válida.", "error")
            elif factura and CompraProveedor.query.filter_by(proveedor_id=proveedor.id, factura=factura).first():
                flash("Ya existe una compra con esa factura para este proveedor.", "error")
            else:
                compra = CompraProveedor(
                    proveedor_id=proveedor.id, usuario_id=current_user.id, fecha=fecha,
                    factura=factura,
                    descripcion=request.form.get("descripcion", "").strip() or None,
                    total=total, forma_pago=forma,
                )
                db.session.add(compra)
                db.session.flush()
                if pagado > 0:
                    pago = PagoCompraProveedor(
                        compra=compra, usuario_id=current_user.id, fecha=fecha,
                        monto=pagado, forma_pago=forma_pago_real,
                    )
                    db.session.add(pago)
                    db.session.add(Egreso(
                        pago_compra=pago, usuario_id=current_user.id,
                        fecha=datetime.combine(fecha, datetime.now(ZONA_HORARIA).time().replace(tzinfo=None)),
                        monto=pagado, concepto=f"Pago a {proveedor.nombre} - factura {compra.factura or compra.id or 'nueva'}",
                        categoria="pago_proveedor", forma_pago=forma_pago_real,
                    ))
                db.session.commit()
                flash("Compra registrada con el saldo pendiente calculado.", "success")
                return redirect(url_for("listar_compras_proveedor"))
        return render_template("compras/form.html", hoy=hoy_argentina())

    @app.route("/compras")
    @login_required
    def listar_compras_proveedor():
        compras = CompraProveedor.query.order_by(CompraProveedor.fecha.desc(), CompraProveedor.id.desc()).all()
        return render_template("compras/index.html", compras=compras)

    @app.route("/compras/<int:compra_id>/pago", methods=["POST"])
    @login_required
    def pagar_compra_proveedor(compra_id):
        compra = CompraProveedor.query.filter_by(id=compra_id).with_for_update().first_or_404()
        monto = decimal_formulario("monto")
        forma = request.form.get("forma_pago", "")
        if monto is None or monto <= 0 or monto > compra.saldo:
            flash("El pago debe ser mayor a cero y no superar el saldo pendiente.", "error")
        elif forma not in {"efectivo", "transferencia", "otro"}:
            flash("Forma de pago inválida.", "error")
        else:
            pago = PagoCompraProveedor(
                compra_id=compra.id, usuario_id=current_user.id,
                fecha=hoy_argentina(), monto=monto, forma_pago=forma,
            )
            db.session.add(pago)
            db.session.add(Egreso(
                pago_compra=pago, usuario_id=current_user.id,
                fecha=datetime.now(ZONA_HORARIA).replace(tzinfo=None), monto=monto,
                concepto=f"Pago a {compra.proveedor.nombre} - factura {compra.factura or compra.id}",
                categoria="pago_proveedor", forma_pago=forma,
            ))
            db.session.commit()
            flash("Pago imputado a la factura.", "success")
        return redirect(url_for("listar_compras_proveedor"))

    @app.route("/egresos/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_egreso():
        if request.method == "POST":
            monto = decimal_formulario("monto")
            concepto = request.form.get("concepto", "").strip()
            categoria = request.form.get("categoria", "")
            forma = request.form.get("forma_pago", "")
            if monto is None or monto <= 0 or not concepto or categoria not in {"retiro", "gasto"} or forma not in {"efectivo", "transferencia", "otro"}:
                flash("Completá el importe, concepto, categoría y forma de pago correctamente.", "error")
            else:
                db.session.add(Egreso(
                    usuario_id=current_user.id, monto=monto, concepto=concepto,
                    categoria=categoria, forma_pago=forma,
                    observaciones=request.form.get("observaciones", "").strip() or None,
                ))
                db.session.commit()
                flash("Egreso registrado.", "success")
                destino = "retiros" if current_user.es_vendedor else "modulo_egresos"
                return redirect(url_for(destino))
        return render_template("egresos/nuevo.html")

    @app.route("/egresos")
    @administrador_requerido
    def modulo_egresos():
        desde_texto, hasta_texto = request.args.get("desde", ""), request.args.get("hasta", "")
        try:
            desde = date.fromisoformat(desde_texto) if desde_texto else hoy_argentina()
            hasta = date.fromisoformat(hasta_texto) if hasta_texto else hoy_argentina()
        except ValueError:
            desde, hasta = hoy_argentina(), hoy_argentina()
        q = Egreso.query.filter(
            Egreso.fecha >= datetime.combine(desde, datetime.min.time()),
            Egreso.fecha < datetime.combine(hasta + timedelta(days=1), datetime.min.time()),
            Egreso.categoria.in_(["retiro", "gasto"]),
            Egreso.usuario_id.is_not(None),
            Egreso.legacy_retiro_id.is_(None),
            Egreso.legacy_pago_proveedor_id.is_(None),
            Egreso.pago_compra_id.is_(None),
        )
        vendedor_id = request.args.get("usuario_id", type=int)
        if vendedor_id:
            q = q.filter_by(usuario_id=vendedor_id)
        categoria_filtro = request.args.get("categoria", "")
        forma_filtro = request.args.get("forma_pago", "")
        if categoria_filtro in {"retiro", "gasto"}:
            q = q.filter_by(categoria=categoria_filtro)
        if forma_filtro in {"efectivo", "transferencia", "otro"}:
            q = q.filter_by(forma_pago=forma_filtro)
        orden = request.args.get("orden", "fecha")
        if orden == "importe":
            q = q.order_by(Egreso.monto.desc(), Egreso.fecha.desc())
        elif orden == "vendedor":
            q = q.outerjoin(Usuario, Egreso.usuario_id == Usuario.id).order_by(Usuario.username, Egreso.fecha.desc())
        elif orden == "categoria":
            q = q.order_by(Egreso.categoria, Egreso.fecha.desc())
        else:
            orden = "fecha"
            q = q.order_by(Egreso.fecha.desc(), Egreso.id.desc())
        egresos = q.all()
        usuarios = Usuario.query.order_by(Usuario.username).all()
        por_usuario = {}
        for e in egresos:
            clave = e.usuario.username if e.usuario else "Sistema"
            fila = por_usuario.setdefault(clave, {"total": Decimal("0.00"), "cantidad": 0})
            fila["total"] += e.monto
            fila["cantidad"] += 1
        egresos_por_usuario = [
            {
                "usuario": nombre,
                "egresos": [
                    e for e in egresos
                    if e.usuario and e.usuario.username == nombre
                ],
            }
            for nombre in sorted(por_usuario)
        ]
        lunes = (hoy_argentina() - timedelta(days=hoy_argentina().weekday()))
        mes = hoy_argentina().replace(day=1)
        total_dia = sum((e.monto for e in egresos if e.fecha.date() == hoy_argentina()), Decimal("0.00"))
        total_semana = sum((e.monto for e in egresos if e.fecha.date() >= lunes and e.fecha.date() <= hoy_argentina()), Decimal("0.00"))
        total_mes = sum((e.monto for e in egresos if e.fecha.date() >= mes and e.fecha.date() <= hoy_argentina()), Decimal("0.00"))
        return render_template("egresos/index.html", egresos=egresos, usuarios=usuarios,
                               desde=desde, hasta=hasta, vendedor_id=vendedor_id,
                               categoria_filtro=categoria_filtro, forma_filtro=forma_filtro,
                               orden=orden,
                               egresos_por_usuario=egresos_por_usuario,
                               total=sum((e.monto for e in egresos), Decimal("0.00")),
                               por_usuario=por_usuario, total_dia=total_dia,
                               total_semana=total_semana, total_mes=total_mes)

    @app.route("/egresos/<int:egreso_id>/editar", methods=["GET", "POST"])
    @administrador_requerido
    def editar_egreso(egreso_id):
        egreso = db.get_or_404(Egreso, egreso_id)
        if egreso.estado != "activo" or egreso.categoria == "pago_proveedor":
            flash("Solo el administrador puede modificar egresos.", "error")
            return redirect(url_for("modulo_egresos"))
        if request.method == "POST":
            monto = decimal_formulario("monto")
            concepto = request.form.get("concepto", "").strip()
            categoria = request.form.get("categoria", "")
            forma = request.form.get("forma_pago", "")
            try:
                fecha_egreso = date.fromisoformat(request.form.get("fecha", ""))
            except ValueError:
                fecha_egreso = None
            if monto is None or monto <= 0 or not concepto or fecha_egreso is None or categoria not in {"retiro", "gasto"} or forma not in {"efectivo", "transferencia", "otro"}:
                flash("Revisá el importe, concepto, categoría y forma de pago.", "error")
            else:
                anterior = {"fecha": egreso.fecha.isoformat(), "monto": str(egreso.monto), "concepto": egreso.concepto, "categoria": egreso.categoria,
                            "forma_pago": egreso.forma_pago, "observaciones": egreso.observaciones}
                nuevo = {"fecha": fecha_egreso.isoformat(), "monto": str(monto), "concepto": concepto, "categoria": categoria,
                         "forma_pago": forma, "observaciones": request.form.get("observaciones", "").strip() or None}
                hora_actual = egreso.fecha.time()
                egreso.fecha = datetime.combine(fecha_egreso, hora_actual)
                egreso.monto, egreso.concepto, egreso.categoria = monto, concepto, categoria
                egreso.forma_pago, egreso.observaciones = forma, nuevo["observaciones"]
                egreso.modificado, egreso.modificado_por_id = datetime.now(ZONA_HORARIA).replace(tzinfo=None), current_user.id
                db.session.add(AuditoriaEgreso(egreso=egreso, usuario_id=current_user.id, anteriores=anterior, nuevos=nuevo))
                db.session.commit()
                flash("Egreso actualizado; quedó guardada la auditoría.", "success")
                return redirect(url_for("modulo_egresos"))
        return render_template("egresos/editar.html", egreso=egreso)

    @app.route("/egresos/reporte.pdf")
    @administrador_requerido
    def egresos_pdf():
        try:
            desde = date.fromisoformat(request.args.get("desde", ""))
            hasta = date.fromisoformat(request.args.get("hasta", ""))
        except ValueError:
            flash("Elegí un rango de fechas válido para generar el PDF.", "error")
            return redirect(url_for("modulo_egresos"))
        if desde > hasta:
            flash("La fecha inicial no puede ser posterior a la fecha final.", "error")
            return redirect(url_for("modulo_egresos"))
        q = Egreso.query.filter(
            Egreso.fecha >= datetime.combine(desde, datetime.min.time()),
            Egreso.fecha < datetime.combine(hasta + timedelta(days=1), datetime.min.time()),
            Egreso.categoria.in_(["retiro", "gasto"]),
            Egreso.usuario_id.is_not(None),
            Egreso.legacy_retiro_id.is_(None),
            Egreso.legacy_pago_proveedor_id.is_(None),
            Egreso.pago_compra_id.is_(None),
        )
        usuario_id = request.args.get("usuario_id", type=int)
        categoria = request.args.get("categoria", "")
        forma = request.args.get("forma_pago", "")
        if usuario_id:
            q = q.filter_by(usuario_id=usuario_id)
        if categoria in {"retiro", "gasto"}:
            q = q.filter_by(categoria=categoria)
        if forma in {"efectivo", "transferencia", "otro"}:
            q = q.filter_by(forma_pago=forma)
        egresos = q.order_by(Egreso.usuario_id, Egreso.fecha).all()
        if not egresos:
            flash("No hay egresos en el período y con los filtros elegidos.", "error")
            return redirect(url_for("modulo_egresos", desde=desde.isoformat(), hasta=hasta.isoformat()))
        pdf = FPDF(orientation="L", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "VERDULERIA EL GAUCHITO - REPORTE DE EGRESOS", ln=1)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, f"Período: {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} | Generado por {current_user.username} | {datetime.now(ZONA_HORARIA):%d/%m/%Y %H:%M}", ln=1)
        pdf.cell(0, 7, f"Movimientos: {len(egresos)} | Total: ${sum((e.monto for e in egresos), Decimal('0.00')):.2f}", ln=1)
        pdf.ln(2)
        columnas = [(27,"Fecha"),(34,"Vendedor"),(25,"Categoría"),(28,"Forma"),(90,"Concepto"),(30,"Importe")]
        pdf.set_font("Helvetica", "B", 9)
        for ancho, titulo in columnas: pdf.cell(ancho, 8, titulo, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
        for e in egresos:
            valores = [e.fecha.strftime("%d/%m/%Y %H:%M"), e.usuario.username if e.usuario else "Sistema", e.categoria, e.forma_pago, e.concepto, f"${e.monto:.2f}"]
            for (ancho, _), valor in zip(columnas, valores): pdf.cell(ancho, 7, str(valor)[:55], border=1)
            pdf.ln()
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 10)
        por_vendedor, por_categoria = {}, {}
        for e in egresos:
            vendedor = e.usuario.username if e.usuario else "Sistema"
            por_vendedor[vendedor] = por_vendedor.get(vendedor, Decimal("0.00")) + e.monto
            por_categoria[e.categoria] = por_categoria.get(e.categoria, Decimal("0.00")) + e.monto
        for vendedor, subtotal in sorted(por_vendedor.items()):
            pdf.cell(0, 7, f"Subtotal {vendedor}: ${subtotal:.2f}", ln=1)
        for tipo, subtotal in sorted(por_categoria.items()):
            pdf.cell(0, 7, f"Subtotal {tipo}: ${subtotal:.2f}", ln=1)
        nombre = f"egresos-{desde:%Y%m%d}-{hasta:%Y%m%d}.pdf"
        contenido_pdf = pdf.output(dest="S")
        if isinstance(contenido_pdf, str):
            contenido_pdf = contenido_pdf.encode("latin-1")
        return send_file(BytesIO(bytes(contenido_pdf)), mimetype="application/pdf", as_attachment=True, download_name=nombre)

    # ------------------------------------------------------------------
    # LOGIN / LOGOUT
    # ------------------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            destino = "dashboard"
            return redirect(url_for(destino))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            usuario = Usuario.query.filter_by(username=username).first()

            if usuario and usuario.check_password(password):
                login_user(usuario, remember=True)
                destino = "dashboard"
                return redirect(url_for(destino))
            flash("Usuario o contraseña incorrectos.", "error")

        return render_template("login.html")

    @app.route("/cuenta", methods=["GET", "POST"])
    @administrador_requerido
    def configurar_cuenta():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password_actual = request.form.get("password_actual", "")
            password_nueva = request.form.get("password_nueva", "")
            password_confirmacion = request.form.get("password_confirmacion", "")

            if not username:
                flash("El nombre de usuario es obligatorio.", "error")
                return render_template("cuenta/configurar.html")

            otro_usuario = Usuario.query.filter(
                Usuario.username == username, Usuario.id != current_user.id
            ).first()
            if otro_usuario:
                flash("Ese nombre de usuario ya está en uso.", "error")
                return render_template("cuenta/configurar.html")

            quiere_cambiar_password = any(
                (password_actual, password_nueva, password_confirmacion)
            )
            if quiere_cambiar_password:
                if not current_user.check_password(password_actual):
                    flash("La contraseña actual es incorrecta.", "error")
                    return render_template("cuenta/configurar.html")
                if not password_nueva:
                    flash("La nueva contraseña no puede estar vacía.", "error")
                    return render_template("cuenta/configurar.html")
                if password_nueva != password_confirmacion:
                    flash("Las nuevas contraseñas no coinciden.", "error")
                    return render_template("cuenta/configurar.html")

                current_user.set_password(password_nueva)

            current_user.username = username
            db.session.commit()
            flash("Datos de acceso actualizados.", "success")
            return redirect(url_for("configurar_cuenta"))

        return render_template("cuenta/configurar.html")

    @app.route("/usuarios/nuevo", methods=["GET", "POST"])
    @administrador_requerido
    def nuevo_usuario():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            rol = request.form.get("rol", "vendedor")

            if not username or not password:
                flash("Usuario y contraseña son obligatorios.", "error")
                return render_template("usuarios/form.html")
            if rol not in ("administrador", "vendedor"):
                flash("Rol inválido.", "error")
                return render_template("usuarios/form.html")
            if Usuario.query.filter_by(username=username).first():
                flash("Ese nombre de usuario ya está en uso.", "error")
                return render_template("usuarios/form.html")

            usuario = Usuario(username=username, rol=rol)
            usuario.set_password(password)
            db.session.add(usuario)
            db.session.commit()
            flash(f"Usuario '{username}' creado como {rol}.", "success")
            return redirect(url_for("nuevo_usuario"))

        return render_template("usuarios/form.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

  

    # ------------------------------------------------------------------
    # DASHBOARD (resumen del día)
    # ------------------------------------------------------------------

    @app.route("/")
    @login_required
    def dashboard():
        hoy = hoy_argentina()
        ventas_hoy = Venta.query.filter_by(fecha=hoy).all()
        totales = totales_por_forma(ventas_hoy)
        total_hoy = round(sum(v.monto for v in ventas_hoy), 2)

        if current_user.es_vendedor:
            clientes = Cliente.query.filter_by(activo=True).all()
            deudas_actuales = sorted(
                [
                    {"cliente": cliente, "monto": cliente.saldo}
                    for cliente in clientes
                    if cliente.saldo > 0
                ],
                key=lambda deuda: deuda["cliente"].nombre.lower(),
            )
            return render_template(
                "dashboard_vendedor.html",
                hoy=hoy,
                ventas_hoy=ventas_hoy,
                total_hoy=total_hoy,
                efectivo_hoy=totales["efectivo"],
                cuenta_hoy=totales["cuenta_corriente"],
                tarjeta_hoy=totales["tarjeta_qr"],
                transferencia_hoy=totales["transferencia"],
                deudas_hoy=deudas_actuales,
                deuda_total_actual=round(
                    sum(deuda["monto"] for deuda in deudas_actuales), 2
                ),
            )

        clientes = Cliente.query.filter_by(activo=True).all()
        deudores = sorted(
            [c for c in clientes if c.saldo > 0],
            key=lambda c: c.saldo,
            reverse=True,
        )
        deuda_total = round(sum(c.saldo for c in deudores), 2)

        efectivo_real_hoy = round(
            totales["efectivo"]
            - totales["tarjeta_qr"]
            - totales["transferencia"]
            - totales["cuenta_corriente"],
            2,
        )

        return render_template(
            "dashboard.html",
            hoy=hoy,
            ventas_hoy=ventas_hoy,
            total_hoy=total_hoy,
            efectivo_hoy=totales["efectivo"],
            cuenta_hoy=totales["cuenta_corriente"],
            tarjeta_hoy=totales["tarjeta_qr"],
            transferencia_hoy=totales["transferencia"],
            efectivo_real_hoy=efectivo_real_hoy,
            deudores=deudores[:5],
            deuda_total=deuda_total,
            cantidad_deudores=len(deudores),
        )

    # ------------------------------------------------------------------
    # CLIENTES
    # ------------------------------------------------------------------

    @app.route("/clientes")
    @administrador_requerido
    def listar_clientes():
        busqueda = request.args.get("q", "").strip()
        clientes_opciones = Cliente.query.filter_by(activo=True).order_by(
            Cliente.nombre
        ).all()
        clientes = []
        if busqueda:
            query = Cliente.query.filter_by(activo=True)
            query = query.filter(Cliente.nombre.ilike(f"%{busqueda}%"))
            clientes = query.order_by(Cliente.nombre).all()
        return render_template(
            "clientes/list.html",
            clientes=clientes,
            clientes_opciones=clientes_opciones,
            busqueda=busqueda,
        )

    @app.route("/clientes/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_cliente():
        volver = request.args.get("volver") == "ventas" or request.form.get("volver") == "ventas"
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            telefono = request.form.get("telefono", "").strip()
            direccion = request.form.get("direccion", "").strip()
            notas = request.form.get("notas", "").strip()
            form_data = {
                "nombre": nombre,
                "telefono": telefono,
                "direccion": direccion,
                "notas": notas,
            }
            cliente = Cliente(
                nombre=nombre,
                telefono=telefono,
                direccion=direccion,
                notas=notas,
            )
            if not cliente.nombre:
                flash("El nombre es obligatorio.", "error")
                return render_template(
                    "clientes/form.html", cliente=None, form_data=form_data,
                    duplicados=[], volver=volver
                )

            nombre_normalizado = " ".join(nombre.casefold().split())
            duplicados = [
                existente
                for existente in Cliente.query.order_by(
                    Cliente.activo.desc(), Cliente.nombre
                ).all()
                if " ".join(existente.nombre.casefold().split()) == nombre_normalizado
            ]
            es_otro = request.form.get("es_otro") == "si"
            tiene_dato_diferenciador = any((telefono, direccion, notas))
            if duplicados and (
                not es_otro or not tiene_dato_diferenciador
            ):
                if es_otro and not tiene_dato_diferenciador:
                    flash(
                        "Para agregarlo como otro cliente, completá teléfono, "
                        "dirección o notas.",
                        "error",
                    )
                return render_template(
                    "clientes/form.html", cliente=None, form_data=form_data,
                    duplicados=duplicados, volver=volver
                )

            db.session.add(cliente)
            db.session.commit()
            flash(f"Cliente '{cliente.nombre}' cargado.", "success")
            if volver or current_user.es_vendedor:
                return redirect(url_for("nueva_venta", cliente_id=cliente.id))
            return redirect(url_for("listar_clientes"))

        return render_template(
            "clientes/form.html", cliente=None, form_data={}, duplicados=[], volver=volver
        )

    @app.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
    @administrador_requerido
    def editar_cliente(cliente_id):
        cliente = db.get_or_404(Cliente, cliente_id)

        if request.method == "POST":
            cliente.nombre = request.form.get("nombre", "").strip()
            cliente.telefono = request.form.get("telefono", "").strip()
            cliente.direccion = request.form.get("direccion", "").strip()
            cliente.notas = request.form.get("notas", "").strip()

            if not cliente.nombre:
                flash("El nombre es obligatorio.", "error")
                return render_template("clientes/form.html", cliente=cliente)

            db.session.commit()
            flash("Cliente actualizado.", "success")
            return redirect(url_for("listar_clientes"))

        return render_template("clientes/form.html", cliente=cliente)

    @app.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
    @administrador_requerido
    def eliminar_cliente(cliente_id):
        # No borramos de verdad (para no perder el historial de ventas):
        # lo marcamos como inactivo y dejamos de mostrarlo en las listas.
        cliente = db.get_or_404(Cliente, cliente_id)
        cliente.activo = False
        db.session.commit()
        flash(f"Cliente '{cliente.nombre}' dado de baja.", "success")
        return redirect(url_for("listar_clientes"))

    # ------------------------------------------------------------------
    # PRODUCTOS DE ALMACEN
    # ------------------------------------------------------------------

    @app.route("/productos/almacen/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_producto_almacen():
        mostrar_costos = current_user.es_administrador
        if request.method == "POST":
            codigo = request.form.get("codigo", "").strip().upper() or None
            nombre = request.form.get("nombre", "").strip()
            categoria = request.form.get("categoria", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            errores = []

            valores = {}
            campos_numericos = [("stock", "stock")]
            if mostrar_costos:
                campos_numericos.extend(
                    [
                        ("precio_costo", "precio de costo"),
                        ("porcentaje_ganancia", "porcentaje de ganancia"),
                    ]
                )
            else:
                campos_numericos.append(("precio_venta", "precio de venta"))

            for campo, etiqueta in campos_numericos:
                texto = request.form.get(campo, "0").strip().replace(",", ".")
                try:
                    valor = Decimal(texto or "0")
                    if not valor.is_finite() or valor < 0:
                        raise InvalidOperation
                    if campo == "porcentaje_ganancia" and valor > 10000:
                        raise InvalidOperation
                    valores[campo] = valor
                except InvalidOperation:
                    errores.append(f"El {etiqueta} debe ser un número igual o mayor a cero.")

            if not nombre:
                errores.append("El nombre del producto es obligatorio.")
            if codigo and ProductoAlmacen.query.filter_by(codigo=codigo).first():
                errores.append("Ya existe un producto con ese código.")

            porcentaje_final = precio_final = None
            if "precio_costo" in valores and "porcentaje_ganancia" in valores:
                porcentaje_final, precio_final, error_precio = resolver_precio(
                    valores["precio_costo"],
                    valores["porcentaje_ganancia"],
                    request.form.get("precio_venta"),
                )
                if error_precio:
                    errores.append(error_precio)

            if errores:
                for error in errores:
                    flash(error, "error")
                return render_template(
                    "productos/form.html", mostrar_costos=mostrar_costos
                )

            if mostrar_costos:
                precio_costo = valores["precio_costo"]
                porcentaje_ganancia = porcentaje_final
                precio_venta = precio_final
            else:
                precio_costo = Decimal("0")
                porcentaje_ganancia = Decimal("0")
                precio_venta = valores["precio_venta"]

            producto = ProductoAlmacen(
                codigo=codigo,
                nombre=nombre,
                categoria=categoria or None,
                descripcion=descripcion or None,
                stock=valores["stock"],
                precio_costo=precio_costo,
                porcentaje_ganancia=porcentaje_ganancia,
                precio_venta=precio_venta,
            )
            db.session.add(producto)
            db.session.commit()
            flash(f"Producto '{producto.nombre}' agregado al almacén.", "success")
            return redirect(url_for("buscar_productos_almacen", q=producto.nombre))

        return render_template(
            "productos/form.html", mostrar_costos=mostrar_costos
        )

    @app.route("/productos/almacen/<int:producto_id>/editar", methods=["GET", "POST"])
    @administrador_requerido
    def editar_producto_almacen(producto_id):
        producto = ProductoAlmacen.query.filter_by(
            id=producto_id, activo=True
        ).first_or_404()

        if request.method == "POST":
            codigo = request.form.get("codigo", "").strip().upper() or None
            nombre = request.form.get("nombre", "").strip()
            categoria = request.form.get("categoria", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            errores = []
            valores = {}

            for campo, etiqueta in (
                ("stock", "stock"),
                ("precio_costo", "precio de costo"),
                ("porcentaje_ganancia", "porcentaje de ganancia"),
            ):
                texto = request.form.get(campo, "").strip().replace(",", ".")
                try:
                    valor = Decimal(texto)
                    if not valor.is_finite() or valor < 0:
                        raise InvalidOperation
                    if campo == "porcentaje_ganancia" and valor > 10000:
                        raise InvalidOperation
                    valores[campo] = valor
                except InvalidOperation:
                    errores.append(f"El {etiqueta} debe ser un número igual o mayor a cero.")

            if not nombre:
                errores.append("El nombre del producto es obligatorio.")

            codigo_existente = ProductoAlmacen.query.filter(
                ProductoAlmacen.codigo == codigo,
                ProductoAlmacen.id != producto.id,
            ).first() if codigo else None
            if codigo_existente and codigo_existente.activo:
                errores.append(
                    f"Ya existe otro producto con ese código: "
                    f"'{codigo_existente.nombre}' (id {codigo_existente.id})."
                )
        
            porcentaje_final = precio_final = None
            if "precio_costo" in valores and "porcentaje_ganancia" in valores:
                porcentaje_final, precio_final, error_precio = resolver_precio(
                    valores["precio_costo"],
                    valores["porcentaje_ganancia"],
                    request.form.get("precio_venta"),
                )
                if error_precio:
                    errores.append(error_precio)


            if errores:
                for error in errores:
                    flash(error, "error")
                return render_template(
                    "productos/form.html",
                    producto=producto,
                    mostrar_costos=True,
                )

            # Si el código lo tiene un producto dado de baja, se lo liberamos
            if codigo_existente and not codigo_existente.activo:
                codigo_existente.codigo = None
                db.session.flush()

            producto.codigo = codigo
            producto.nombre = nombre
            producto.categoria = categoria or None
            producto.descripcion = descripcion or None
            producto.stock = valores["stock"]
            producto.precio_costo = valores["precio_costo"]
            producto.porcentaje_ganancia = porcentaje_final
            producto.precio_venta = precio_final

            db.session.commit()
            flash(f"Producto '{producto.nombre}' actualizado.", "success")
            return redirect(url_for("buscar_productos_almacen", q=producto.nombre))

        return render_template(
            "productos/form.html", producto=producto, mostrar_costos=True
        )

    @app.route("/productos/almacen/<int:producto_id>/eliminar", methods=["POST"])
    @administrador_requerido
    def eliminar_producto_almacen(producto_id):
        producto = ProductoAlmacen.query.filter_by(
            id=producto_id, activo=True
        ).first_or_404()
        producto.activo = False
        db.session.commit()
        flash(f"Producto '{producto.nombre}' dado de baja.", "success")
        return redirect(url_for("buscar_productos_almacen"))

    @app.route("/productos/almacen/sugerencias")
    @login_required
    def sugerencias_productos_almacen():
        termino = request.args.get("q", "").strip()
        if not termino:
            return jsonify({"productos": []})

        palabras = [normalizar(p) for p in termino.split()]
        productos = (
            ProductoAlmacen.query.filter(ProductoAlmacen.activo.is_(True))
            .order_by(ProductoAlmacen.nombre)
            .all()
        )
        coinciden = [
            p.nombre for p in productos
            if all(palabra in normalizar(p.nombre) for palabra in palabras)
        ]
        return jsonify({"productos": coinciden[:30]})

    @app.route("/productos/almacen/buscar")
    @login_required
    def buscar_productos_almacen():
        busqueda = request.args.get("q", "").strip()
        productos = (
            ProductoAlmacen.query.filter_by(activo=True)
            .order_by(ProductoAlmacen.nombre)
            .all()
        )
        palabras = [normalizar(p) for p in busqueda.split()]
        if palabras:
            productos = [
                p for p in productos
                if all(
                    palabra in normalizar(
                        " ".join(filter(None, [p.nombre, p.codigo, p.categoria, p.descripcion]))
                    )
                    for palabra in palabras
                )
            ]
        return render_template(
            "productos/list.html",
            productos=productos,
            busqueda=busqueda,
            modo="buscar",
            mostrar_costos=current_user.es_administrador,
        )

    @app.route("/productos/almacen/lista-precios")
    @login_required
    def imprimir_lista_precios():
        productos = (
            ProductoAlmacen.query.filter_by(activo=True)
            .order_by(ProductoAlmacen.nombre)
            .all()
        )
        return render_template(
            "productos/list.html",
            productos=productos,
            busqueda="",
            modo="precios",
            mostrar_costos=False,
        )

    # ------------------------------------------------------------------
    # PRODUCTOS DE VERDULERIA
    # ------------------------------------------------------------------

    @app.route("/productos/verduleria/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_producto_verduleria():
        mostrar_costos = current_user.es_administrador
        if request.method == "POST":
            codigo = request.form.get("codigo", "").strip().upper() or None
            nombre = request.form.get("nombre", "").strip()
            categoria = request.form.get("categoria", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            errores = []

            valores = {}
            campos_numericos = [("stock", "stock")]
            if mostrar_costos:
                campos_numericos.extend(
                    [
                        ("precio_costo", "precio de costo"),
                        ("porcentaje_ganancia", "porcentaje de ganancia"),
                    ]
                )
            else:
                campos_numericos.append(("precio_venta", "precio de venta"))

            for campo, etiqueta in campos_numericos:
                texto = request.form.get(campo, "0").strip().replace(",", ".")
                try:
                    valor = Decimal(texto or "0")
                    if not valor.is_finite() or valor < 0:
                        raise InvalidOperation
                    if campo == "porcentaje_ganancia" and valor > 10000:
                        raise InvalidOperation
                    valores[campo] = valor
                except InvalidOperation:
                    errores.append(f"El {etiqueta} debe ser un número igual o mayor a cero.")

            if not nombre:
                errores.append("El nombre del producto es obligatorio.")
            if codigo and ProductoVerduleria.query.filter_by(codigo=codigo).first():
                errores.append("Ya existe un producto con ese código.")

            porcentaje_final = precio_final = None
            if "precio_costo" in valores and "porcentaje_ganancia" in valores:
                porcentaje_final, precio_final, error_precio = resolver_precio(
                    valores["precio_costo"],
                    valores["porcentaje_ganancia"],
                    request.form.get("precio_venta"),
                )
                if error_precio:
                    errores.append(error_precio)

        
            if errores:
                for error in errores:
                    flash(error, "error")
                return render_template(
                    "productos/form_verduleria.html", mostrar_costos=mostrar_costos
                )

            if mostrar_costos:
                precio_costo = valores["precio_costo"]
                porcentaje_ganancia = porcentaje_final
                precio_venta = precio_final
            else:
                precio_costo = Decimal("0")
                porcentaje_ganancia = Decimal("0")
                precio_venta = valores["precio_venta"]

            producto = ProductoVerduleria(
                codigo=codigo,
                nombre=nombre,
                categoria=categoria or None,
                descripcion=descripcion or None,
                stock=valores["stock"],
                precio_costo=precio_costo,
                porcentaje_ganancia=porcentaje_ganancia,
                precio_venta=precio_venta,
            )
            db.session.add(producto)
            db.session.commit()
            flash(f"Producto '{producto.nombre}' agregado a verdulería.", "success")
            return redirect(url_for("buscar_productos_verduleria", q=producto.nombre))

        return render_template(
            "productos/form_verduleria.html", mostrar_costos=mostrar_costos
        )

    @app.route("/productos/verduleria/<int:producto_id>/editar", methods=["GET", "POST"])
    @administrador_requerido
    def editar_producto_verduleria(producto_id):
        producto = ProductoVerduleria.query.filter_by(
            id=producto_id, activo=True
        ).first_or_404()

        if request.method == "POST":
            codigo = request.form.get("codigo", "").strip().upper() or None
            nombre = request.form.get("nombre", "").strip()
            categoria = request.form.get("categoria", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            errores = []
            valores = {}

            for campo, etiqueta in (
                ("stock", "stock"),
                ("precio_costo", "precio de costo"),
                ("porcentaje_ganancia", "porcentaje de ganancia"),
            ):
                texto = request.form.get(campo, "").strip().replace(",", ".")
                try:
                    valor = Decimal(texto)
                    if not valor.is_finite() or valor < 0:
                        raise InvalidOperation
                    if campo == "porcentaje_ganancia" and valor > 10000:
                        raise InvalidOperation
                    valores[campo] = valor
                except InvalidOperation:
                    errores.append(f"El {etiqueta} debe ser un número igual o mayor a cero.")

            if not nombre:
                errores.append("El nombre del producto es obligatorio.")

            codigo_existente = ProductoVerduleria.query.filter(
                ProductoVerduleria.codigo == codigo,
                ProductoVerduleria.id != producto.id,
            ).first() if codigo else None
            if codigo_existente and codigo_existente.activo:
                errores.append(
                    f"Ya existe otro producto con ese código: "
                    f"'{codigo_existente.nombre}' (id {codigo_existente.id})."
                )

            porcentaje_final = precio_final = None
            if "precio_costo" in valores and "porcentaje_ganancia" in valores:
                porcentaje_final, precio_final, error_precio = resolver_precio(
                    valores["precio_costo"],
                    valores["porcentaje_ganancia"],
                    request.form.get("precio_venta"),
                )
                if error_precio:
                    errores.append(error_precio)

            if errores:
                for error in errores:
                    flash(error, "error")
                return render_template(
                    "productos/form_verduleria.html",
                    producto=producto,
                    mostrar_costos=True,
                )

            if codigo_existente and not codigo_existente.activo:
                codigo_existente.codigo = None
                db.session.flush()

            producto.codigo = codigo
            producto.nombre = nombre
            producto.categoria = categoria or None
            producto.descripcion = descripcion or None
            producto.stock = valores["stock"]
            producto.precio_costo = valores["precio_costo"]
            producto.porcentaje_ganancia = porcentaje_final
            producto.precio_venta = precio_final

            db.session.commit()
            flash(f"Producto '{producto.nombre}' actualizado.", "success")
            return redirect(url_for("buscar_productos_verduleria", q=producto.nombre))

        return render_template(
            "productos/form_verduleria.html", producto=producto, mostrar_costos=True
        )

    @app.route("/productos/verduleria/<int:producto_id>/eliminar", methods=["POST"])
    @administrador_requerido
    def eliminar_producto_verduleria(producto_id):
        producto = ProductoVerduleria.query.filter_by(
            id=producto_id, activo=True
        ).first_or_404()
        producto.activo = False
        db.session.commit()
        flash(f"Producto '{producto.nombre}' dado de baja.", "success")
        return redirect(url_for("buscar_productos_verduleria"))

    @app.route("/productos/verduleria/sugerencias")
    @login_required
    def sugerencias_productos_verduleria():
        termino = request.args.get("q", "").strip()
        if not termino:
            return jsonify({"productos": []})

        palabras = [normalizar(p) for p in termino.split()]
        productos = (
            ProductoVerduleria.query.filter(ProductoVerduleria.activo.is_(True))
            .order_by(ProductoVerduleria.nombre)
            .all()
        )
        coinciden = [
            p.nombre for p in productos
            if all(palabra in normalizar(p.nombre) for palabra in palabras)
        ]
        return jsonify({"productos": coinciden[:30]})

    @app.route("/productos/verduleria/buscar")
    @login_required
    def buscar_productos_verduleria():
        busqueda = request.args.get("q", "").strip()
        productos = (
            ProductoVerduleria.query.filter_by(activo=True)
            .order_by(ProductoVerduleria.nombre)
            .all()
        )
        palabras = [normalizar(p) for p in busqueda.split()]
        if palabras:
            productos = [
                p for p in productos
                if all(
                    palabra in normalizar(
                        " ".join(filter(None, [p.nombre, p.codigo, p.categoria, p.descripcion]))
                    )
                    for palabra in palabras
                )
            ]
        return render_template(
            "productos/list_verduleria.html",
            productos=productos,
            busqueda=busqueda,
            modo="buscar",
            mostrar_costos=current_user.es_administrador,
        )

    @app.route("/productos/verduleria/lista-precios")
    @login_required
    def imprimir_lista_precios_verduleria():
        productos = (
            ProductoVerduleria.query.filter_by(activo=True)
            .order_by(ProductoVerduleria.nombre)
            .all()
        )
        return render_template(
            "productos/list_verduleria.html",
            productos=productos,
            busqueda="",
            modo="precios",
            mostrar_costos=False,
        )

    # ------------------------------------------------------------------
    # VENTAS
    # ------------------------------------------------------------------

    @app.route("/ventas")
    @administrador_requerido
    def listar_ventas():
        fecha_str = request.args.get("fecha", hoy_argentina().isoformat())
        try:
            fecha_filtro = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            fecha_filtro = hoy_argentina()

        ventas = (
            Venta.query.filter_by(fecha=fecha_filtro)
            .order_by(Venta.creado.desc())
            .all()
        )
        total = round(sum(v.monto for v in ventas), 2)
        return render_template(
            "ventas/list.html", ventas=ventas, fecha_filtro=fecha_filtro, total=total
        )

    @app.route("/ventas/nueva", methods=["GET", "POST"])
    @login_required
    def nueva_venta():
        clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
        cliente_seleccionado = None
        cliente_id_inicial = request.args.get("cliente_id", type=int)
        if cliente_id_inicial:
            cliente_seleccionado = Cliente.query.filter_by(
                id=cliente_id_inicial, activo=True
            ).first()

        if request.method == "POST":
            cliente_id = request.form.get("cliente_id", type=int)
            monto = request.form.get("monto", type=float)
            descripcion = request.form.get("descripcion", "").strip()
            forma_pago = request.form.get("forma_pago", "efectivo")
            if current_user.es_vendedor:
                fecha_venta = hoy_argentina()
            else:
                fecha_str = request.form.get("fecha") or hoy_argentina().isoformat()
                fecha_venta = datetime.strptime(fecha_str, "%Y-%m-%d").date()

            errores = []
            if not cliente_id:
                errores.append("Elegí un cliente.")
            elif not any(cliente.id == cliente_id for cliente in clientes):
                errores.append("Elegí un cliente activo de la lista.")
            if not monto or monto <= 0:
                errores.append("El monto tiene que ser mayor a 0.")
            if forma_pago not in FORMAS_PAGO:
                errores.append("Forma de pago inválida.")

            if errores:
                for e in errores:
                    flash(e, "error")
                cliente_seleccionado = next(
                    (cliente for cliente in clientes if cliente.id == cliente_id),
                    None,
                )
                return render_template(
                    "ventas/form.html",
                    clientes=clientes,
                    cliente_seleccionado=cliente_seleccionado,
                    fecha_inicial=fecha_venta,
                )

            venta = Venta(
                cliente_id=cliente_id,
                usuario_id=current_user.id,
                fecha=fecha_venta,
                descripcion=descripcion,
                monto=monto,
                forma_pago=forma_pago,
            )
            db.session.add(venta)
            db.session.flush()  # así "venta" ya tiene un id antes del commit

            # Si la venta es a cuenta corriente, esto genera automáticamente
            # la deuda: un movimiento tipo "venta" que suma al saldo del cliente.
            if forma_pago == "cuenta_corriente":
                movimiento = MovimientoCC(
                    cliente_id=cliente_id,
                    venta_id=venta.id,
                    usuario_id=current_user.id,
                    fecha=fecha_venta,
                    tipo="venta",
                    monto=monto,
                    descripcion=descripcion or "Venta a cuenta corriente",
                )
                db.session.add(movimiento)

            db.session.commit()
            flash("Venta registrada.", "success")
            if current_user.es_vendedor:
                return redirect(url_for("dashboard"))
            return redirect(url_for("listar_ventas", fecha=fecha_venta.isoformat()))

        return render_template(
            "ventas/form.html",
            clientes=clientes,
            cliente_seleccionado=cliente_seleccionado,
            fecha_inicial=hoy_argentina(),
        )

    @app.route("/ventas/<int:venta_id>/editar", methods=["GET", "POST"])
    @administrador_requerido

    def editar_venta(venta_id):
        venta = db.get_or_404(Venta, venta_id)
        clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()

        if request.method == "POST":
            cliente_id = request.form.get("cliente_id", type=int)
            monto = request.form.get("monto", type=float)
            descripcion = request.form.get("descripcion", "").strip()
            forma_pago = request.form.get("forma_pago", "efectivo")
            fecha_str = request.form.get("fecha") or venta.fecha.isoformat()
            fecha_venta = datetime.strptime(fecha_str, "%Y-%m-%d").date()

            errores = []
            if not cliente_id:
                errores.append("Elegí un cliente.")
            if not monto or monto <= 0:
                errores.append("El monto tiene que ser mayor a 0.")
            if forma_pago not in FORMAS_PAGO:                
                errores.append("Forma de pago inválida.")

            if errores:
                for e in errores:
                    flash(e, "error")
                return render_template(
                    "ventas/form.html", clientes=clientes,
                    cliente_seleccionado=venta.cliente, venta=venta,
                    fecha_inicial=venta.fecha,
                )

            # Si ya tenía un movimiento de cuenta corriente asociado, lo borramos
            # para recrearlo (o no) según los datos nuevos.
            movimiento_existente = MovimientoCC.query.filter_by(venta_id=venta.id).first()
            if movimiento_existente:
                db.session.delete(movimiento_existente)

            venta.cliente_id = cliente_id
            venta.fecha = fecha_venta
            venta.descripcion = descripcion
            venta.monto = monto
            venta.forma_pago = forma_pago

            if forma_pago == "cuenta_corriente":
                nuevo_movimiento = MovimientoCC(
                    cliente_id=cliente_id,
                    venta_id=venta.id,
                    fecha=fecha_venta,
                    tipo="venta",
                    monto=monto,
                    descripcion=descripcion or "Venta a cuenta corriente",
                )
                db.session.add(nuevo_movimiento)

            db.session.commit()
            flash("Venta actualizada.", "success")
            return redirect(url_for("listar_ventas", fecha=fecha_venta.isoformat()))

        return render_template(
            "ventas/form.html", clientes=clientes,
            cliente_seleccionado=venta.cliente, venta=venta,
            fecha_inicial=venta.fecha,
        )

    @app.route("/ventas/<int:venta_id>/eliminar", methods=["POST"])
    @administrador_requerido
    def eliminar_venta(venta_id):
        venta = db.get_or_404(Venta, venta_id)
        movimiento = MovimientoCC.query.filter_by(venta_id=venta.id).first()
        if movimiento:
            db.session.delete(movimiento)
        fecha = venta.fecha
        db.session.delete(venta)
        db.session.commit()
        flash("Venta eliminada.", "success")
        return redirect(url_for("listar_ventas", fecha=fecha.isoformat()))

    # ------------------------------------------------------------------
    # RETIROS (proveedores y retiros del vendedor)
    # ------------------------------------------------------------------

    @app.route("/retiros")
    @login_required
    def retiros():
        if current_user.es_administrador:
            return redirect(url_for("modulo_egresos"))
        hoy = hoy_argentina()
        inicio = datetime.combine(hoy, datetime.min.time())
        fin = datetime.combine(hoy + timedelta(days=1), datetime.min.time())
        retiros_hoy = Egreso.query.filter(
            Egreso.usuario_id == current_user.id,
            Egreso.categoria == "retiro",
            Egreso.fecha >= inicio,
            Egreso.fecha < fin,
        ).order_by(Egreso.fecha.desc(), Egreso.id.desc()).all()
        return render_template(
            "egresos/retiros_hoy.html", hoy=hoy, retiros_hoy=retiros_hoy,
            total_retiros_hoy=sum((r.monto for r in retiros_hoy), Decimal("0.00")),
        )
        hoy = hoy_argentina()
        proveedores = Proveedor.query.filter_by(activo=True).order_by(Proveedor.nombre).all()
        resumen = []
        for p in proveedores:
            cuenta = round(sum(x.monto for x in p.pagos if x.tipo == "cuenta_corriente"), 2)
            pagado = round(sum(x.monto for x in p.pagos if x.tipo != "cuenta_corriente"), 2)
            resumen.append({
                "proveedor": p,
                "cuenta": cuenta,
                "pagado": pagado,
                "debe": max(round(cuenta - pagado, 2), 0),
            })
        egresos_hoy = (
            PagoProveedor.query.filter_by(fecha=hoy)
            .order_by(PagoProveedor.creado.desc()).all()
        )
        retiros_hoy = (
            RetiroVendedor.query.filter_by(fecha=hoy, usuario_id=current_user.id)
            .order_by(RetiroVendedor.creado.desc()).all()
        )
        return render_template(
            "retiros/index.html",
            hoy=hoy,
            resumen=resumen,
            egresos_hoy=egresos_hoy,
            retiros_hoy=retiros_hoy,
            total_pagado_hoy=round(sum(e.monto for e in egresos_hoy if e.tipo != "cuenta_corriente"), 2),
            total_cc_hoy=round(sum(e.monto for e in egresos_hoy if e.tipo == "cuenta_corriente"), 2),
            total_retiros_hoy=round(sum(r.monto for r in retiros_hoy), 2),
        )

    @app.route("/retiros/proveedores/nuevo", methods=["POST"])
    @login_required
    def alta_proveedor():
        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            flash("Escribí el nombre del proveedor.", "error")
            return redirect(url_for("retiros"))
        existentes = Proveedor.query.filter_by(activo=True).all()
        if any(normalizar(p.nombre) == normalizar(nombre) for p in existentes):
            flash("Ya existe un proveedor con ese nombre.", "error")
            return redirect(url_for("retiros"))
        db.session.add(Proveedor(nombre=nombre))
        db.session.commit()
        flash(f"Proveedor '{nombre}' agregado.", "success")
        return redirect(url_for("retiros"))

    @app.route("/retiros/proveedores/<int:proveedor_id>/editar", methods=["GET", "POST"])
    @administrador_requerido
    def editar_proveedor(proveedor_id):
        proveedor = Proveedor.query.filter_by(id=proveedor_id, activo=True).first_or_404()
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            if not nombre:
                flash("El nombre es obligatorio.", "error")
                return render_template("retiros/proveedor_editar.html", proveedor=proveedor)
            otros = Proveedor.query.filter(
                Proveedor.activo.is_(True), Proveedor.id != proveedor.id
            ).all()
            if any(normalizar(p.nombre) == normalizar(nombre) for p in otros):
                flash("Ya existe otro proveedor con ese nombre.", "error")
                return render_template("retiros/proveedor_editar.html", proveedor=proveedor)
            proveedor.nombre = nombre
            proveedor.telefono = request.form.get("telefono", "").strip() or None
            db.session.commit()
            flash("Proveedor actualizado.", "success")
            return redirect(url_for("retiros"))
        return render_template("retiros/proveedor_editar.html", proveedor=proveedor)

    @app.route("/retiros/proveedores/<int:proveedor_id>/eliminar", methods=["POST"])
    @administrador_requerido
    def baja_proveedor(proveedor_id):
        proveedor = Proveedor.query.filter_by(id=proveedor_id, activo=True).first_or_404()
        proveedor.activo = False  # se conserva el historial de pagos
        db.session.commit()
        flash(f"Proveedor '{proveedor.nombre}' dado de baja.", "success")
        return redirect(url_for("retiros"))

    @app.route("/retiros/egresos/nuevo", methods=["POST"])
    @login_required
    def nuevo_egreso_proveedor():
        flash("Los pagos a proveedores se registran desde Compras y se imputan a una factura.", "error")
        return redirect(url_for("listar_compras_proveedor"))
        proveedor_id = request.form.get("proveedor_id", type=int)
        tipo = request.form.get("tipo", "")
        monto = request.form.get("monto", type=float)
        descripcion = request.form.get("descripcion", "").strip()
        proveedor = Proveedor.query.filter_by(id=proveedor_id, activo=True).first() if proveedor_id else None
        if not proveedor:
            flash("Elegí un proveedor.", "error")
        elif tipo not in TIPOS_EGRESO:
            flash("Elegí el tipo de pago.", "error")
        elif not monto or monto <= 0:
            flash("El monto tiene que ser mayor a 0.", "error")
        else:
            db.session.add(PagoProveedor(
                proveedor_id=proveedor.id, usuario_id=current_user.id,
                fecha=hoy_argentina(), tipo=tipo, monto=monto,
                descripcion=descripcion or None,
            ))
            db.session.commit()
            flash(f"{TIPOS_EGRESO[tipo]} a {proveedor.nombre} registrado: ${monto:,.2f}.", "success")
        return redirect(url_for("retiros"))

    @app.route("/retiros/vendedor/nuevo", methods=["POST"])
    @login_required
    def nuevo_retiro_vendedor():
        monto = decimal_formulario("monto")
        descripcion = request.form.get("descripcion", "").strip()
        if monto is None or monto <= 0:
            flash("El monto del retiro tiene que ser mayor a 0.", "error")
        else:
            db.session.add(Egreso(usuario_id=current_user.id, monto=monto,
                                  concepto=descripcion or "Retiro del vendedor",
                                  categoria="retiro", forma_pago="efectivo"))
            db.session.commit()
            flash(f"Retiro de ${monto:,.2f} registrado.", "success")
        return redirect(url_for("retiros"))
        monto = request.form.get("monto", type=float)
        descripcion = request.form.get("descripcion", "").strip()
        if not monto or monto <= 0:
            flash("El monto del retiro tiene que ser mayor a 0.", "error")
        else:
            db.session.add(RetiroVendedor(
                usuario_id=current_user.id, fecha=hoy_argentina(),
                monto=monto, descripcion=descripcion or None,
            ))
            db.session.commit()
            flash(f"Retiro de ${monto:,.2f} registrado.", "success")
        return redirect(url_for("retiros"))

    # ------------------------------------------------------------------
    # CUENTA CORRIENTE
    # ------------------------------------------------------------------

    @app.route("/cuenta-corriente")
    @administrador_requerido
    def cuenta_corriente_index():
        clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
        clientes = sorted(
            [c for c in clientes if c.saldo > 0],
            key=lambda c: c.saldo,
            reverse=True,
        )
        deuda_total = round(sum(cliente.saldo for cliente in clientes), 2)
        return render_template(
            "cuenta/index.html", clientes=clientes, deuda_total=deuda_total
        )

    @app.route("/cuenta-corriente/<int:cliente_id>")
    @administrador_requerido
    def cuenta_corriente_detalle(cliente_id):
        cliente = db.get_or_404(Cliente, cliente_id)
        movimientos = sorted(cliente.movimientos, key=lambda m: (m.fecha, m.creado))

        # Armamos el saldo "corrido" (como en un resumen bancario), para
        # que se vea cómo fue subiendo o bajando la deuda con cada movimiento.
        saldo_corrido = 0.0
        filas = []
        for m in movimientos:
            saldo_corrido += m.monto if m.tipo == "venta" else -m.monto
            filas.append({"mov": m, "saldo": round(saldo_corrido, 2)})
        filas.reverse()  # mostramos lo más reciente primero

        return render_template("cuenta/detalle.html", cliente=cliente, filas=filas)

    @app.route("/cuenta-corriente/<int:cliente_id>/pago", methods=["POST"])
    @login_required
    def registrar_pago(cliente_id):
        cliente = db.get_or_404(Cliente, cliente_id)
        monto = request.form.get("monto", type=float)
        descripcion = request.form.get("descripcion", "").strip()
        if current_user.es_vendedor:
            fecha_pago = hoy_argentina()
        else:
            fecha_str = request.form.get("fecha") or hoy_argentina().isoformat()
            fecha_pago = datetime.strptime(fecha_str, "%Y-%m-%d").date()

        if not monto or monto <= 0:
            flash("El monto del pago tiene que ser mayor a 0.", "error")
            if current_user.es_vendedor:
                return redirect(url_for("registrar_pago_vendedor"))
            return redirect(url_for("cuenta_corriente_detalle", cliente_id=cliente_id))
        if current_user.es_vendedor and cliente.saldo <= 0:
            flash("El cliente no tiene deuda pendiente.", "error")
            return redirect(url_for("registrar_pago_vendedor"))
        if current_user.es_vendedor and monto > cliente.saldo:
            flash("El pago no puede superar la deuda pendiente.", "error")
            return redirect(url_for("registrar_pago_vendedor"))

        movimiento = MovimientoCC(
            cliente_id=cliente_id,
            usuario_id=current_user.id,
            fecha=fecha_pago,
            tipo="pago",
            monto=monto,
            descripcion=descripcion or "Pago / abono",
        )
        db.session.add(movimiento)
        db.session.commit()
        print(
            f"[PAGO] Usuario={current_user.username} Cliente={cliente.nombre} "
            f"Monto=${monto:,.2f} Fecha={fecha_pago.isoformat()}",
            flush=True,
        )
        flash(f"Pago de ${monto:,.2f} registrado.", "success")
        if current_user.es_vendedor:
            return redirect(url_for("dashboard"))
        return redirect(url_for("cuenta_corriente_detalle", cliente_id=cliente_id))

    @app.route("/pagos/nuevo", methods=["GET", "POST"])
    @login_required
    def registrar_pago_vendedor():
        clientes = [
            cliente
            for cliente in Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
            if cliente.saldo > 0
        ]
        movimientos_por_cliente = {
            cliente.id: [
                {
                    "tipo": movimiento.tipo,
                    "monto": f"{movimiento.monto:.2f}",
                    "fecha": movimiento.fecha.strftime("%d/%m/%Y"),
                    "hora": movimiento.creado.strftime("%H:%M"),
                    "descripcion": movimiento.descripcion or "Sin descripción",
                }
                for movimiento in sorted(
                    cliente.movimientos,
                    key=lambda movimiento: (movimiento.fecha, movimiento.creado),
                    reverse=True,
                )
            ]
            for cliente in clientes
        }

        if request.method == "POST":
            cliente_id = request.form.get("cliente_id", type=int)
            if not cliente_id or not any(cliente.id == cliente_id for cliente in clientes):
                flash("Elegí un cliente con deuda pendiente.", "error")
                return redirect(url_for("registrar_pago_vendedor"))
            return registrar_pago(cliente_id)

        return render_template(
            "pagos/form.html",
            clientes=clientes,
            fecha_inicial=hoy_argentina(),
            movimientos_por_cliente=movimientos_por_cliente,
        )

    @app.route("/notificaciones/pagos")
    @administrador_requerido
    def notificaciones_pagos():
        desde_id = request.args.get("desde_id", 0, type=int)
        inicializar = request.args.get("inicializar") == "1"
        ultimo_pago = MovimientoCC.query.filter_by(tipo="pago").order_by(
            MovimientoCC.id.desc()
        ).first()
        ultimo_id = ultimo_pago.id if ultimo_pago else 0

        if inicializar:
            return jsonify({"pagos": [], "ultimo_id": ultimo_id})

        pagos = (
            MovimientoCC.query.filter(
                MovimientoCC.tipo == "pago", MovimientoCC.id > desde_id
            )
            .order_by(MovimientoCC.id)
            .limit(20)
            .all()
        )
        return jsonify(
            {
                "pagos": [
                    {
                        "id": pago.id,
                        "cliente": pago.cliente.nombre,
                        "monto": f"{pago.monto:,.2f}",
                        "fecha": pago.fecha.strftime("%d/%m/%Y"),
                        "hora": pago.creado.strftime("%H:%M:%S"),
                        "descripcion": pago.descripcion or "Pago / abono",
                    }
                    for pago in pagos
                ],
                "ultimo_id": ultimo_id,
            }
        )

    @app.route("/notificaciones/pagos/lista")
    @administrador_requerido
    def lista_pagos_recibidos():
        pagos = (
            MovimientoCC.query.filter_by(tipo="pago")
            .order_by(MovimientoCC.creado.desc())
            .all()
        )
        return render_template("pagos/recibidos.html", pagos=pagos)

    @app.route("/deudores")
    @login_required
    def listar_deudores():
        deudores = [
            cliente
            for cliente in Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
            if cliente.saldo > 0
        ]
        return render_template(
            "pagos/deudores.html",
            deudores=deudores,
            deuda_total=round(sum(cliente.saldo for cliente in deudores), 2),
        )

    # ------------------------------------------------------------------
    # REPORTES
    # ------------------------------------------------------------------

    @app.route("/reportes")
    @administrador_requerido
    def reportes():
        hoy = hoy_argentina()
        desde_str = request.args.get("desde", hoy.isoformat())
        hasta_str = request.args.get("hasta", hoy.isoformat())

        desde = datetime.strptime(desde_str, "%Y-%m-%d").date()
        hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date()

        # --- Reporte de ventas en el rango ---
        ventas = (
            Venta.query.filter(Venta.fecha >= desde, Venta.fecha <= hasta)
            .order_by(Venta.fecha)
            .all()
        )
        total_ventas = round(sum(v.monto for v in ventas), 2)
        totales = totales_por_forma(ventas)
        total_efectivo = totales["efectivo"]
        total_cuenta = totales["cuenta_corriente"]
        total_tarjeta = totales["tarjeta_qr"]
        total_transferencia = totales["transferencia"]

        # Ventas agrupadas por día (para un mini-resumen día a día)
        ventas_por_dia = {}
        for v in ventas:
            ventas_por_dia.setdefault(v.fecha, []).append(v)
        resumen_diario = [
            {"fecha": f, "total": round(sum(v.monto for v in vs), 2), "cantidad": len(vs)}
            for f, vs in sorted(ventas_por_dia.items())
        ]

        # --- Reporte de deudas: movimientos de cuenta corriente en el rango ---
        movimientos = (
            MovimientoCC.query.filter(
                MovimientoCC.fecha >= desde, MovimientoCC.fecha <= hasta
            )
            .order_by(MovimientoCC.fecha)
            .all()
        )
        cargos = round(sum(m.monto for m in movimientos if m.tipo == "venta"), 2)
        pagos = round(sum(m.monto for m in movimientos if m.tipo == "pago"), 2)

        # Deuda total actual (a hoy, no depende del rango) por cliente
        clientes = Cliente.query.filter_by(activo=True).all()
        deudores = sorted(
            [c for c in clientes if c.saldo > 0], key=lambda c: c.saldo, reverse=True
        )
        deuda_total_actual = round(sum(c.saldo for c in deudores), 2)

        return render_template(
            "reportes/index.html",
            desde=desde,
            hasta=hasta,
            total_ventas=total_ventas,
            total_efectivo=total_efectivo,
            total_cuenta=total_cuenta,
            total_tarjeta=total_tarjeta,
            total_transferencia=total_transferencia,
            ventas=ventas,
            resumen_diario=resumen_diario,
            cargos=cargos,
            pagos=pagos,
            deudores=deudores,
            deuda_total_actual=deuda_total_actual,
        )

    @app.route("/reportes/pdf")
    @administrador_requerido
    def reportes_pdf():
        hoy = hoy_argentina()
        desde_str = request.args.get("desde", hoy.isoformat())
        hasta_str = request.args.get("hasta", hoy.isoformat())
        desde = datetime.strptime(desde_str, "%Y-%m-%d").date()
        hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date()

        ventas = (
            Venta.query.filter(Venta.fecha >= desde, Venta.fecha <= hasta)
            .order_by(Venta.fecha, Venta.creado)
            .all()
        )

        verde = (8, 125, 53)
        rojo = (190, 30, 45)
        verde_claro = (220, 239, 220)
        gris_claro = (245, 246, 248)
        gris_texto = (90, 100, 110)
        

        pdf = FPDF()
        pdf.add_page()

        pdf.set_fill_color(*rojo)
        pdf.rect(0, 0, 210, 26, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 7)
        pdf.cell(0, 8, "VERDULERIA EL GAUCHITO", ln=1)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_x(10)
        pdf.cell(0, 6, "Detalle de ventas", ln=1)

        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(10, 32)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*gris_texto)
        pdf.cell(0, 6, f"Periodo: {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}", ln=1)
        pdf.cell(0, 6, f"Generado el {hoy_argentina().strftime('%d/%m/%Y')} a las {datetime.now(ZONA_HORARIA).strftime('%H:%M')}", ln=1)
        pdf.ln(4)

        anchos = [18, 14, 26, 28, 30, 18, 20]
        encabezados = ["Fecha", "Hora", "Cliente", "Usuario", "Descripcion", "Forma", "Monto"]
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(*rojo)
        pdf.set_text_color(255, 255, 255)
        for ancho, texto in zip(anchos, encabezados):
            pdf.cell(ancho, 8, texto, border=0, fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(0, 0, 0)
        total = 0.0
        for i, venta in enumerate(ventas):
            total += venta.monto
            if i % 2 == 0:
                pdf.set_fill_color(*gris_claro)
            else:
                pdf.set_fill_color(255, 255, 255)
            fila = [
                venta.fecha.strftime("%d/%m/%Y"),
                venta.creado.strftime("%H:%M"),
                venta.cliente.nombre[:18],
                (venta.usuario.username if venta.usuario else "Sistema")[:14],
                (venta.descripcion or "Sin descripcion")[:26],
                FORMAS_PAGO.get(venta.forma_pago, venta.forma_pago),
                f"${venta.monto:,.2f}",
            ]
            for ancho, texto in zip(anchos, fila):
                pdf.cell(ancho, 7, texto, border=0, fill=True)
            pdf.ln()

        pdf.set_fill_color(*verde_claro)
        pdf.set_text_color(*verde)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(sum(anchos[:-1]), 9, "Total", border=0, fill=True)
        pdf.cell(anchos[-1], 9, f"${total:,.2f}", border=0, fill=True)

        buffer = BytesIO(bytes(pdf.output()))
        nombre_archivo = f"detalle-ventas_{desde.isoformat()}_{hasta.isoformat()}.pdf"
        return send_file(
            buffer, mimetype="application/pdf",
            as_attachment=True, download_name=nombre_archivo,
        )

    @app.route("/reportes/deudores/pdf")
    @administrador_requerido
    def deudores_pdf():
        clientes = Cliente.query.filter_by(activo=True).all()
        deudores = sorted(
            [c for c in clientes if c.saldo > 0], key=lambda c: c.saldo, reverse=True
        )

        verde = (8, 125, 53)
        rojo = (190, 30, 45)          # <-- nuevo
        ladrillo = (155, 48, 48)
        gris_claro = (245, 246, 248)
        gris_texto = (90, 100, 110)

        pdf = FPDF()
        anchos = [18, 14, 18, 24, 22, 20, 22]
        encabezados = ["Fecha", "Hora", "Tipo", "Usuario", "Descripcion", "Monto", "Saldo"]

        for cliente in deudores:
            pdf.add_page()

            pdf.set_fill_color(*rojo)
            pdf.rect(0, 0, 210, 26, "F")
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_xy(10, 7)
            pdf.cell(0, 8, "VERDULERIA EL GAUCHITO", ln=1)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_x(10)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(0, 7, cliente.nombre, ln=1)

            pdf.set_xy(10, 32)
            pdf.set_font("Helvetica", "", 13)
            pdf.set_text_color(*gris_texto)
            pdf.cell(0, 6, f"Generado el {hoy_argentina().strftime('%d/%m/%Y')} a las {datetime.now(ZONA_HORARIA).strftime('%H:%M')}", ln=1)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(*ladrillo)
            pdf.cell(0, 8, f"Deuda actual: ${cliente.saldo:,.2f}", ln=1)
            pdf.ln(4)

            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(*rojo)
            pdf.set_text_color(255, 255, 255)
            for ancho, texto in zip(anchos, encabezados):
                pdf.cell(ancho, 8, texto, border=0, fill=True)
            pdf.ln()

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(0, 0, 0)
            movimientos = sorted(cliente.movimientos, key=lambda m: (m.fecha, m.creado))
            saldo_corrido = 0.0
            for i, m in enumerate(movimientos):
                saldo_corrido += m.monto if m.tipo == "venta" else -m.monto
                pdf.set_fill_color(*gris_claro) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
                fila = [
                    m.fecha.strftime("%d/%m/%Y"),
                    m.creado.strftime("%H:%M"),
                    "Venta" if m.tipo == "venta" else "Pago",
                    (m.usuario.username if m.usuario else "Sistema")[:14],
                    (m.descripcion or "Sin descripcion")[:22],
                    f"${m.monto:,.2f}",
                    f"${saldo_corrido:,.2f}",
                ]
                for ancho, texto in zip(anchos, fila):
                    pdf.cell(ancho, 7, texto, border=0, fill=True)
                pdf.ln()

        buffer = BytesIO(bytes(pdf.output()))
        return send_file(
            buffer, mimetype="application/pdf",
            as_attachment=True, download_name="clientes-con-deuda.pdf",
        )
    
    return app


app = create_app()


if __name__ == "__main__":
    # host="0.0.0.0" es lo que permite entrar desde el celular (ver README.md).
    # debug=True reinicia el servidor solo cuando guardás un cambio de código
    # (muy útil mientras aprendés, pero se desactiva en producción real).
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
    )
