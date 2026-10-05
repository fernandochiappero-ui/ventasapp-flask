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

from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, send_file
from fpdf import FPDF
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from functools import wraps
from sqlalchemy import inspect, or_, text
from extensions import db, login_manager
from models import Usuario, Cliente, Venta, MovimientoCC, ProductoAlmacen

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")
def hoy_argentina(): return datetime.now(ZONA_HORARIA).date()

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "cambia-esta-clave-por-una-propia"
    )

    # Le decimos a SQLAlchemy que use un archivo SQLite (una base de
    # datos liviana que es un solo archivo, ideal para un proyecto chico).
    database_url = os.environ.get("DATABASE_URL", "sqlite:///base_datos.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
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
                total_hoy=round(sum(v.monto for v in ventas_hoy), 2),
                efectivo_hoy=round(
                    sum(v.monto for v in ventas_hoy if v.forma_pago == "efectivo"), 2
                ),
                cuenta_hoy=round(
                    sum(
                        v.monto
                        for v in ventas_hoy
                        if v.forma_pago == "cuenta_corriente"
                    ),
                    2,
                ),
                deudas_hoy=deudas_actuales,
                deuda_total_actual=round(
                    sum(deuda["monto"] for deuda in deudas_actuales), 2
                ),
            )

        total_hoy = round(sum(v.monto for v in ventas_hoy), 2)
        efectivo_hoy = round(
            sum(v.monto for v in ventas_hoy if v.forma_pago == "efectivo"), 2
        )
        cuenta_hoy = round(
            sum(v.monto for v in ventas_hoy if v.forma_pago == "cuenta_corriente"), 2
        )

        # Clientes con saldo pendiente (deuda), ordenados de mayor a menor
        clientes = Cliente.query.filter_by(activo=True).all()
        deudores = sorted(
            [c for c in clientes if c.saldo > 0],
            key=lambda c: c.saldo,
            reverse=True,
        )
        deuda_total = round(sum(c.saldo for c in deudores), 2)

        return render_template(
            "dashboard.html",
            hoy=hoy,
            ventas_hoy=ventas_hoy,
            total_hoy=total_hoy,
            efectivo_hoy=efectivo_hoy,
            cuenta_hoy=cuenta_hoy,
            deudores=deudores[:5],  # top 5 en el resumen
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

            if errores:
                for error in errores:
                    flash(error, "error")
                return render_template(
                    "productos/form.html", mostrar_costos=mostrar_costos
                )

            if mostrar_costos:
                precio_costo = valores["precio_costo"]
                porcentaje_ganancia = valores["porcentaje_ganancia"]
                precio_venta = (
                    precio_costo * (Decimal("1") + porcentaje_ganancia / Decimal("100"))
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
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
            if codigo_existente:
                errores.append("Ya existe otro producto con ese código.")

            if errores:
                for error in errores:
                    flash(error, "error")
                return render_template(
                    "productos/form.html",
                    producto=producto,
                    mostrar_costos=True,
                )

            producto.codigo = codigo
            producto.nombre = nombre
            producto.categoria = categoria or None
            producto.descripcion = descripcion or None
            producto.stock = valores["stock"]
            producto.precio_costo = valores["precio_costo"]
            producto.porcentaje_ganancia = valores["porcentaje_ganancia"]
            producto.precio_venta = (
                producto.precio_costo
                * (Decimal("1") + producto.porcentaje_ganancia / Decimal("100"))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
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

        productos = (
            ProductoAlmacen.query.filter(
                ProductoAlmacen.activo.is_(True),
                ProductoAlmacen.nombre.ilike(f"%{termino}%"),
            )
            .order_by(ProductoAlmacen.nombre)
            .limit(30)
            .all()
        )
        return jsonify({"productos": [producto.nombre for producto in productos]})

    @app.route("/productos/almacen/buscar")
    @login_required
    def buscar_productos_almacen():
        busqueda = request.args.get("q", "").strip()
        consulta = ProductoAlmacen.query.filter_by(activo=True)
        if busqueda:
            patron = f"%{busqueda}%"
            consulta = consulta.filter(
                or_(
                    ProductoAlmacen.nombre.ilike(patron),
                    ProductoAlmacen.codigo.ilike(patron),
                    ProductoAlmacen.categoria.ilike(patron),
                )
            )
        productos = consulta.order_by(ProductoAlmacen.nombre).all()
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
            if forma_pago not in ("efectivo", "cuenta_corriente"):
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
            if forma_pago not in ("efectivo", "cuenta_corriente"):
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
        desde_str = request.args.get("desde", (hoy - timedelta(days=7)).isoformat())
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
        total_efectivo = round(
            sum(v.monto for v in ventas if v.forma_pago == "efectivo"), 2
        )
        total_cuenta = round(
            sum(v.monto for v in ventas if v.forma_pago == "cuenta_corriente"), 2
        )

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
        desde_str = request.args.get("desde", (hoy - timedelta(days=7)).isoformat())
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
                "Efectivo" if venta.forma_pago == "efectivo" else "Cta.Cte.",
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

        vverde = (8, 125, 53)
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
            pdf.set_fill_color(*verde)
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
