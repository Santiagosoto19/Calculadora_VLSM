# Calculadora VLSM

Calculadora local de subredes IPv4 (VLSM) e IPv6. El plan se arma en el navegador o por terminal, y se puede exportar a Excel, CSV, JSON y Markdown.

Los reportes se generan en el equipo. No hace falta una cuenta ni un servidor externo.

## Requisitos

- Python 3.10 o superior
- Linux (el arranque usa `setup.sh`)

## Arranque

```bash
./setup.sh
```

Crea `.venv`, instala las dependencias y abre la interfaz en http://127.0.0.1:8501.

Si el entorno ya está instalado:

```bash
.venv/bin/python -m streamlit run app.py
```

Solo instalar, sin abrir la ventana:

```bash
./setup.sh --install-only
```

## Interfaz

En la barra lateral se elige IPv4 o IPv6 y se puede cargar un laboratorio `.md`.

La pantalla tiene cuatro pestañas:

- **Calculadora.** Bloque base, orden de la tabla y las subredes (nombre y hosts).
- **Resultados.** Métricas, tabla de subredes y memoria del cálculo.
- **Diagrama del bloque.** Cómo se reparte el espacio.
- **Exportar.** Excel, CSV, JSON y Markdown.

En IPv4 hay dos modos de hoja:

- **Un listado.** Un solo bloque, por ejemplo `192.168.10.0/24`.
- **Varios grupos.** Varios edificios en una hoja. El botón «Cargar laboratorio Tendencias» usa `examples/tendencias.md` (`172.16.128.0/21`, prefijo de grupo `/23`).

El fondo de la aplicación es blanco.

## Laboratorio en Markdown

Un archivo `.md` puede traer todo el enunciado. En la app se carga desde la barra lateral. En la terminal se usa `--from-md`.

Grupos IPv4:

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

Listado IPv4: `Modo: listado` y una sola sección `## Subredes`.

IPv6 con prefijo fijo:

```markdown
- Protocolo: IPv6
- Base: 2001:db8:abcd::/48
- Modo: fijo
- Prefijo hijo: 64
- Cantidad: 8
```

IPv6 por dispositivos: `Modo: dispositivos`, `Nibble: si` o `no`, y `## Subredes` con columnas `Nombre` y `Dispositivos`.

`--from-md` es la entrada. `--md` es el informe de salida. No se mezclan con el CIDR ni con `-s` / `-g` en el mismo comando.

El ejemplo completo está en `examples/tendencias.md`.

## Terminal

```bash
.venv/bin/python cli.py ipv4 192.168.10.0/24 -s LAN:100 -s WAN:2 --excel plan.xlsx

.venv/bin/python cli.py ipv4 --from-md examples/tendencias.md --excel tendencias.xlsx

.venv/bin/python cli.py ipv6 2001:db8:abcd::/48 --prefix 64 --count 4 --json plan.json
```

Con `setup.sh`:

```bash
./setup.sh --cli -- ipv4 192.168.10.0/24 -s LAN:100 -s WAN:2
```

Opciones útiles de IPv4: `-s Nombre:hosts`, `-g 'Grupo=A:10,B:5'`, `--group-prefix`, `--input-order`, `--excel`, `--csv`, `--json`, `--md`.

Opciones útiles de IPv6: `--prefix`, `--count`, `-s Nombre:dispositivos`, `--nibble-align`.

## Qué calcula

En IPv4 cada subred pide hosts útiles. El bloque asignado es la potencia de 2 que cubre hosts + 2 (red y broadcast), salvo `/31` y `/32`. Por defecto se atiende primero la subred más grande. «Respetar el orden de la tabla» conserva el orden del enunciado.

En IPv6 se puede delegar un prefijo fijo (`/64`, `/127`) o calcular el prefijo según la cantidad de dispositivos.
