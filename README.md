# Libro de Ventas — app web para clientes, ventas y cuenta corriente

Aplicación web hecha con **Python + Flask**. Corre en tu PC (o en cualquier
compu de tu casa/negocio conectada a wifi) y podés abrirla tanto desde la
PC como desde el celular, porque **es una página web**: no hay que instalar
nada en el teléfono, solo abrir el navegador.

## Qué hace

- Login de usuario (usuario y contraseña).
- Cargar y editar clientes.
- Cargar ventas diarias (efectivo o a cuenta corriente).
- Cuenta corriente por cliente: ve el saldo, el historial de movimientos,
  y podés registrar pagos/abonos.
- Reportes de ventas y de deudas, del día o por rango de fechas.
- Diseño mobile-first: pensado primero para el celular, pero se ve bien
  también en la PC (el menú pasa de barra inferior a barra lateral).

---

## 1. Instalación (una sola vez)

### 1.1. Requisitos
- Tener [Python 3.10+](https://www.python.org/downloads/) instalado.
  En Windows, al instalar, tildá la casilla **"Add Python to PATH"**.
- Tener [VS Code](https://code.visualstudio.com/) instalado, con la
  extensión oficial **Python** (de Microsoft) instalada desde el
  ícono de extensiones (el de los cuadraditos, a la izquierda).

### 1.2. Abrir el proyecto en VS Code
1. Abrí VS Code.
2. Archivo → Abrir carpeta... → elegí la carpeta `ventasapp`.
3. Abrí una terminal integrada: menú **Terminal → Nueva terminal**
   (o `Ctrl + ñ` / `Ctrl + backtick`).

### 1.3. Crear un entorno virtual
Un "entorno virtual" es una carpeta aislada donde se instalan las
librerías de este proyecto, para no mezclarlas con otras cosas de tu PC.
En la terminal de VS Code:

```bash
python -m venv .venv
```

Activarlo:

- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`
- **Windows (cmd):** `.venv\Scripts\activate.bat`
- **Mac / Linux:** `source .venv/bin/activate`

Vas a ver `(.venv)` al principio de la línea de la terminal: significa
que está activado. VS Code también te va a preguntar/mostrar abajo a la
derecha si querés usar ese entorno como intérprete de Python: decile que sí
(o elegilo manualmente con `Ctrl+Shift+P` → "Python: Select Interpreter").

### 1.4. Instalar las librerías necesarias
 
```bash
pip install -r requirements.txt
```

Esto instala Flask (el framework web), Flask-SQLAlchemy (para hablar con
la base de datos) y Flask-Login (para el sistema de login).

### 1.5. Crear la base de datos y tu usuario

```bash
python init_db.py
```
Tu Nombre <tu-email@ejemplo.com>
Te va a pedir un nombre de usuario (podés dejar "admin" apretando Enter)
y una contraseña. Con eso ya tenés todo listo. Esto crea un archivo
`instance/base_datos.db` — ahí vive toda tu información (SQLite es una
base de datos que es, literalmente, un solo archivo).

### 1.6. Recuperar una contraseña olvidada

Si olvidaste la contraseña, no borres la base de datos. Ejecutá:

```bash
python reset_password.py
```

Elegí el usuario y escribí dos veces la nueva contraseña. Este proceso
no borra clientes, ventas ni movimientos.

### 1.7. Usuarios y permisos

El administrador puede acceder a todas las pantallas y crear usuarios desde
el menú **Usuarios**. Al crear un usuario se puede elegir:

- **Administrador**: acceso completo.
- **Vendedor**: solo puede cargar ventas y agregar clientes.

Los usuarios existentes se consideran administradores automáticamente al
actualizar la aplicación.

---

## 2. Uso diario

### 2.1. Publicar en Internet con Render

El proyecto incluye `render.yaml` para desplegarlo en Render con PostgreSQL,
una base de datos persistente. En Render:

1. Subí este proyecto a un repositorio de GitHub.
2. Creá un Blueprint nuevo y seleccioná ese repositorio.
3. Render leerá `render.yaml`, instalará las dependencias y creará la base.
4. Abrí la URL HTTPS que Render asigne para usarla desde la PC o el celular,
   incluso en redes diferentes.

No uses `FLASK_DEBUG=1` en producción. La base SQLite local no se copia sola a
PostgreSQL; antes de publicar, creá nuevamente el usuario administrador en la
base de Render con `init_db.py` o mediante un comando de consola del servicio.

### 2.2. Uso diario

#### Levantar el servidor

En la terminal de VS Code (con el entorno `.venv` activado):

```bash
python app.py
```

Vas a ver algo como:

```
* Running on http://127.0.0.1:5000
* Running on http://192.168.0.15:5000
```

- La primera dirección (`127.0.0.1:5000`) es para abrir **desde la
  misma PC**: copiala en el navegador (Chrome, Edge, Firefox).
- La segunda (`192.168.x.x:5000`) es la dirección de tu PC **dentro de
  tu red wifi**: esa es la que usás desde el celular (ver punto 2.2).

Para **detener** el servidor: click en la terminal y `Ctrl + C`.

### 2.2. Usarlo desde el celular

Con el servidor corriendo en la PC:

1. Conectá el celular a **la misma red wifi** que la PC (esto es clave:
   ambos tienen que estar en la misma red).
2. En el celular, abrí el navegador y escribí la segunda dirección que
   mostró la terminal, por ejemplo: `http://192.168.0.15:5000`
3. Te va a aparecer la pantalla de login. Iniciá sesión con el usuario
   que creaste en el paso 1.5.
4. Tip: desde el navegador del celular podés usar la opción
   "Agregar a pantalla de inicio" para que quede como un ícono más,
   como si fuera una app.

> Si no te conecta desde el celular, revisá el firewall de Windows: la
> primera vez que corrés `python app.py` puede aparecer un cartel
> preguntando si permitís el acceso en redes privadas — hay que
> aceptarlo. También fijate que la PC y el celular estén en la misma
> red (no uno en wifi de datos móviles y el otro en wifi de casa).

### 2.3. ¿Cómo sé la IP de mi PC si no la veo en la terminal?
- Windows: `ipconfig` en una terminal, buscar "Dirección IPv4".
- Mac/Linux: `ifconfig` o `ip addr`, buscar algo tipo `192.168.x.x`.

---

## 3. Estructura del proyecto (para ir entendiendo el código)

```
ventasapp/
├── app.py                 → El servidor: define las "rutas" (URLs) y la lógica
├── models.py               → Las tablas de la base de datos (Cliente, Venta, etc.)
├── extensions.py           → Configuración compartida de Flask-SQLAlchemy/Login
├── init_db.py               → Script para crear la base de datos y el primer usuario
├── reset_password.py        → Script para recuperar una contraseña olvidada
├── requirements.txt        → Lista de librerías necesarias
├── instance/
│   └── base_datos.db        → Tu base de datos (se crea sola, no se toca a mano)
├── static/
│   └── css/style.css        → Todo el diseño visual (colores, tamaños, mobile/PC)
└── templates/               → Los archivos HTML que arma cada pantalla
    ├── base.html              → El "molde" común (menú, mensajes) que heredan los demás
    ├── login.html
    ├── dashboard.html          → Pantalla de inicio
    ├── clientes/
    │   ├── list.html
    │   └── form.html
    ├── ventas/
    │   ├── list.html
    │   └── form.html
    ├── cuenta/
    │   ├── index.html
    │   └── detalle.html
    └── reportes/
        └── index.html
```

### 3.1. Cómo funciona Flask, en criollo

Cada vez que el navegador pide una dirección (por ejemplo, cuando entrás
a `/clientes`), Flask busca en `app.py` una función marcada con
`@app.route("/clientes")` y la ejecuta. Esa función:

1. Busca datos en la base de datos (usando los modelos de `models.py`).
2. Le pasa esos datos a un archivo HTML de `templates/` con
   `render_template(...)`.
3. El HTML usa `{{ variable }}` para mostrar datos y `{% for %}` /
   `{% if %}` para repetir o mostrar cosas condicionalmente (esto se
   llama motor de plantillas **Jinja2**, viene incluido con Flask).

Por ejemplo, el flujo cuando cargás una venta a cuenta corriente:
`nueva_venta()` en `app.py` crea una fila en la tabla `Venta` **y
además** crea automáticamente una fila en `MovimientoCC` con
`tipo="venta"`, que es lo que hace que el saldo del cliente suba. Podés
ver esa lógica comentada en `app.py`, dentro de la función
`nueva_venta`.

### 3.2. La base de datos

Son 4 tablas, todas definidas en `models.py`:

- **Usuario**: quién puede loguearse.
- **Cliente**: nombre, teléfono, dirección.
- **Venta**: cada venta cargada (a quién, cuánto, en qué fecha, si fue
  efectivo o cuenta corriente).
- **MovimientoCC**: el "libro mayor" de la cuenta corriente. Cada vez
  que hay una venta a cuenta, se agrega un movimiento tipo `"venta"`
  (suma deuda); cada vez que registrás un pago, se agrega uno tipo
  `"pago"` (resta deuda). El saldo del cliente (propiedad `saldo` en
  `Cliente`, dentro de `models.py`) es simplemente la suma de todos
  esos movimientos.

Guardar cada movimiento por separado (en vez de un solo número de
"saldo actual") es lo que permite armar el historial completo y los
reportes por rango de fechas.

### 3.3. Cómo seguir aprendiendo/modificando

- Para agregar un campo nuevo a un cliente (por ejemplo, email):
  1. Agregalo en `models.py` dentro de la clase `Cliente`.
  2. Agregalo al formulario en `templates/clientes/form.html`.
  3. Agregalo en las funciones `nuevo_cliente` y `editar_cliente` de
     `app.py` (donde se lee `request.form.get(...)`).
  4. Como ya existe la base de datos, hay que recrear la tabla o migrar
     (para este proyecto chico, lo más simple es borrar
     `instance/base_datos.db` y correr `python init_db.py` de nuevo —
     ojo que eso borra los datos cargados).
- Todo el texto de colores/tamaños está en `static/css/style.css`, con
  comentarios arriba de cada sección.
- `debug=True` en `app.py` hace que el servidor se reinicie solo cada
  vez que guardás un cambio de código — no hace falta parar y volver a
  correr `python app.py` a mano mientras estás probando.

---

## 4. Preguntas frecuentes

**¿Los datos se pierden si apago la PC?**
No. Todo queda guardado en `instance/base_datos.db`. Lo que sí necesitás
es volver a correr `python app.py` cada vez que quieras usar la app.

**¿Puedo tener más de un usuario?**
Sí. Corré de nuevo `python init_db.py`: como ya existe un usuario, el
script no te va a dejar crear otro por ahí. La forma más simple para
un segundo usuario es agregar un pequeño script aparte o pedirlo en
otra conversación — con lo que ya tenés en `models.py` (`Usuario`,
`set_password`) alcanza para crearlo por código.

**¿Esto lo puedo usar sin wifi / con datos móviles?**
No tal cual está: el celular necesita llegar a la PC por la red local
(wifi). Para usarlo desde cualquier lado (sin estar en la misma red) hay
que "publicarlo" en internet (por ejemplo con un servicio de hosting),
que es un paso más avanzado — avisame si más adelante querés ese paso
y lo armamos.

**Cambié algo en el código y no se ve reflejado.**
Fijate que el servidor siga corriendo (`python app.py` en la terminal)
y refrescá el navegador. Si cambiaste `models.py` puede que necesites
recrear la base de datos (ver punto 3.3).
