# Calculadora VLSM

Calculadora de direccionamiento IPv4 (VLSM) e IPv6. Sirve para armar el plan de un laboratorio: bloque base, subredes, máscaras, rangos útiles y el espacio que sobra. El mismo cálculo se puede hacer en el navegador o por terminal, y el resultado se descarga en Excel, CSV, JSON o Markdown.

No usa base de datos ni cuentas. En tu máquina el servidor escucha solo en localhost. Si la publicas en Streamlit Community Cloud, el cálculo corre en los servidores de Streamlit y el archivo se descarga en el navegador de quien la use.

## Qué hace

- **IPv4, un listado.** Un bloque (`192.168.10.0/24`) y una tabla de subredes con los hosts que necesita cada una.
- **IPv4, varios grupos.** Varios edificios o sedes dentro del mismo bloque. El Excel sale en una sola hoja, con la tabla a la izquierda y el cálculo binario a la derecha.
- **IPv6.** Prefijo fijo (por ejemplo `/48` partido en `/64`) o prefijo según la cantidad de dispositivos. Se puede alinear a nibble.
- **Entrada en Markdown.** Un solo archivo trae el protocolo, el bloque y las tablas.
- **Salida.** Excel con el paso a paso, más CSV, JSON y Markdown.

Cada subred IPv4 pide hosts útiles. El bloque asignado es la potencia de 2 que cubre hosts + 2 (dirección de red y broadcast). Por defecto se atiende primero la subred más grande. La opción «Respetar el orden de la tabla» conserva el orden del enunciado.

## Requisitos

- Python 3.10 o superior
- Para el arranque con `./setup.sh`, un shell bash (Linux o macOS)

En Windows se puede crear el entorno a mano; los comandos están más abajo.

## Instalación local

Desde la carpeta del proyecto:

```bash
./setup.sh
```

Eso crea `.venv`, instala `requirements.txt` y abre la interfaz en http://127.0.0.1:8501. El script deja el servidor solo en localhost.

Si las dependencias ya están instaladas:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Solo instalar, sin abrir el navegador:

```bash
./setup.sh --install-only
source .venv/bin/activate
```

En Windows, desde PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

`VLSM_HOST` y `VLSM_PORT` cambian el host y el puerto de `./setup.sh`. `PYTHON_BIN` elige el intérprete si `python3` no es el que quieres.

## Interfaz

La barra lateral tiene el cargador de laboratorio (`.md`), una guía corta, el protocolo y el botón de reinicio. Reiniciar vacía el formulario. Si el archivo Markdown sigue cargado, no se vuelve a aplicar hasta que lo quites.

Cuatro pestañas:

| Pestaña | Contenido |
| --- | --- |
| Calculadora | Bloque base, orden y tabla de subredes |
| Resultados | Métricas, tabla calculada y memoria del cálculo |
| Diagrama del bloque | Reparto del espacio entre subredes y lo que queda libre |
| Exportar | Excel, CSV, JSON y Markdown |

En IPv4, «Un listado» es una sola tabla. «Varios grupos (una hoja)» apila edificios. El botón **Cargar laboratorio Tendencias** lee `examples/tendencias.md`: bloque `172.16.128.0/21`, cada edificio en `/23`, orden de la tabla. **Cargar ejemplo** rellena un listado corto, sin ese laboratorio.

Un CIDR inválido o un bloque que no alcanza se muestran en la misma pantalla, con el mensaje del cálculo. No hace falta volver a lanzar el programa.

## Laboratorio en Markdown

Campos, uno por línea, antes del primer `##`:

| Campo | Valores | Cuándo |
| --- | --- | --- |
| Protocolo | `IPv4` o `IPv6` | Siempre |
| Base | CIDR, con `/` | Siempre |
| Modo | `listado`, `grupos`, `fijo`, `dispositivos` | Siempre. IPv4 usa los dos primeros; IPv6, los dos últimos |
| Orden | `tabla` o `tamaño` | Solo IPv4. Si falta, se ordena por tamaño |
| Prefijo grupo | 8–30 | Solo `grupos`. Si falta, el tamaño de cada edificio se calcula solo |
| Prefijo hijo | 1–128 | Obligatorio en `fijo` |
| Cantidad | 1–4096 | `fijo` sin tabla de nombres. Si faltan las dos cosas, lista 8 |
| Nibble | `si`, `sí` o `no` | Solo `dispositivos`. Si falta, no alinea |

En `listado`, `dispositivos` y prefijo fijo con nombres, la única sección es `## Subredes`. En `grupos`, cada `##` es un edificio (de 2 a 12). No mezcles `## Subredes` con otros títulos.

Grupos:

```markdown
# Laboratorio

- Protocolo: IPv4
- Base: 172.16.128.0/21
- Modo: grupos
- Prefijo grupo: 23
- Orden: tabla

## Edificio 1

| Nombre | Hosts |
| --- | --- |
| Area de RRHH | 66 |
| Ventas | 38 |
```

Listado:

```markdown
- Protocolo: IPv4
- Base: 192.168.10.0/24
- Modo: listado

## Subredes

| Nombre | Hosts |
| --- | --- |
| LAN | 100 |
| Servidores | 50 |
```

IPv6, prefijo fijo:

```markdown
- Protocolo: IPv6
- Base: 2001:db8:abcd::/48
- Modo: fijo
- Prefijo hijo: 64
- Cantidad: 8
```

IPv6 por dispositivos: `Modo: dispositivos`, `Nibble: no` y una tabla `Nombre` / `Dispositivos` bajo `## Subredes`.

El enunciado completo de Tendencias está en `examples/tendencias.md`. Si una línea está mal, el error indica el número de línea.

## Terminal

```bash
.venv/bin/python cli.py ipv4 192.168.10.0/24 -s LAN:100 -s WAN:2 --excel plan.xlsx

.venv/bin/python cli.py ipv4 --from-md examples/tendencias.md --excel tendencias.xlsx

.venv/bin/python cli.py ipv6 2001:db8:abcd::/48 --prefix 64 --count 4 --json plan.json

.venv/bin/python cli.py ipv6 fd00:1::/56 -s VLAN10:500 -s P2P:2 --nibble-align
```

También:

```bash
./setup.sh --cli -- ipv4 192.168.10.0/24 -s LAN:100 -s WAN:2
```

`--from-md` lee el laboratorio. `--md` escribe el informe. No van juntos con el CIDR ni con `-s` o `-g`.

IPv4: `-s Nombre:hosts`, `-g 'Grupo=A:10,B:5'`, `--group-prefix`, `--input-order`, `--excel`, `--csv`, `--json`, `--md`, `--relaxed`.

IPv6: `--prefix`, `--count`, `--name`, `-s Nombre:dispositivos`, `--nibble-align`, `--limit`.

## Excel

El libro IPv4 imita el formato de un laboratorio por sedes: tabla de subredes a la izquierda y, en las mismas filas, la rejilla de 32 bits. Arriba hay una tabla `2^n` con fórmulas. Los bits del prefijo padre, los de la subred y los de host van en colores distintos. La hoja IPv6 es una tabla de prefijos, sin esa rejilla.

## Estructura

```text
app.py                  Interfaz Streamlit
cli.py                  Terminal
setup.sh                Entorno local y arranque
requirements.txt        Dependencias
examples/tendencias.md  Laboratorio de ejemplo
core/vlsm_v4.py         Cálculo IPv4
core/subnet_v6.py       Cálculo IPv6
core/md_input.py        Lectura del Markdown
core/excel_exporter.py  Libro Excel
core/reports.py         CSV, JSON y Markdown
assets/app.css          Estilos
.streamlit/config.toml  Tema y opciones del servidor
```

## Despliegue

La vía directa es [Streamlit Community Cloud](https://share.streamlit.io). El proyecto ya tiene `app.py` en la raíz y `requirements.txt`. No hay secretos que configurar.

Community Cloud copia el repositorio y ejecuta `streamlit run app.py`. Por eso `.streamlit/config.toml` no fija `address` ni el puerto: en local los pone `setup.sh`, y en la nube los pone la plataforma. Si se dejaran en `127.0.0.1`, la app publicada no abriría.

Pasos:

1. Sube este repositorio a GitHub, en una rama pública (`main` o `master`).
2. Entra en https://share.streamlit.io con esa cuenta de GitHub.
3. **Create app** → **Yup, I have an app**.
4. Elige el repositorio, la rama y el archivo `app.py`.
5. En **Advanced settings**, elige **Python 3.12**. Community Cloud no usa `runtime.txt`; la versión se elige ahí. 3.12 es la que trae por defecto y cubre las dependencias de este proyecto.
6. No hace falta pegar secretos. Guarda y despliega.

La URL queda en un subdominio `*.streamlit.app`. Cada push a esa rama vuelve a publicar la app. El primer despliegue tarda unos minutos mientras instala `requirements.txt`.

Qué no subir: `.venv/`, `__pycache__/`, `.env` y los `.xlsx` generados. Ya están en `.gitignore`.

## Solución de problemas

| Síntoma | Qué revisar |
| --- | --- |
| `./setup.sh` dice que falta Python | Instala Python 3.10+ o exporta `PYTHON_BIN` |
| El puerto 8501 está ocupado | `VLSM_PORT=8502 ./setup.sh` |
| El Markdown no carga | El archivo tiene que ser UTF-8 y seguir la tabla de campos |
| En la nube la app no abre | `config.toml` no debe fijar `server.address` en `127.0.0.1` |
| Faltan paquetes en la nube | `requirements.txt` está en la raíz, junto a `app.py` |
