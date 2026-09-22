# La Cinta: guía para publicarla gratis

La Cinta es un sitio que explica en español lo que las empresas grandes de la bolsa de EE. UU. presentan ante la SEC.

Con esta guía queda en internet **sin pagar nada**. No hace falta saber programar: todo se hace desde el navegador.

## Qué hace cada parte

| Parte | Qué hace | Costo |
|---|---|---|
| `index.html`, `assets/` | El sitio que ven los visitantes | Gratis (GitHub Pages) |
| `scripts/sec_alertas.py` | Lee la SEC, clasifica los documentos y escribe las explicaciones | Gratis |
| `.github/workflows/…` | Corre el script solo, cada 10 minutos | Gratis (GitHub Actions) |
| `empresas.txt` | La lista de empresas que se vigilan | — |
| `data/alertas.json` | Las alertas que muestra el sitio (se actualiza solo) | — |

**Fuente de datos:** SEC EDGAR. Es información pública, gratis y se puede volver a publicar. El sitio no muestra precios de acciones, así que no necesita licencias de datos de mercado.

## Paso 1: crear la cuenta y el repositorio

1. Crea una cuenta gratis en <https://github.com>.
2. Arriba a la derecha, pulsa **+** y luego **New repository**.
3. Ponle de nombre `la-cinta`, márcalo como **Public** y pulsa **Create repository**.
4. En la página nueva, pulsa **uploading an existing file**.
5. Arrastra **todo el contenido** de la carpeta `la-cinta-sitio`: `index.html`, `assets`, `data`, `scripts`, `empresas.txt`, `LEEME.md` y `.nojekyll`.
6. Pulsa **Commit changes**.

> **Importante:** la carpeta `.github` empieza con punto y a veces el navegador no la sube al arrastrar. Revisa si aparece en el repositorio. Si no aparece:
> 1. Pulsa **Add file** y luego **Create new file**.
> 2. En el nombre escribe `.github/workflows/actualizar-alertas.yml`.
> 3. Pega el contenido del archivo del mismo nombre que viene en la carpeta.
> 4. Guarda con **Commit changes**.

## Paso 2: poner tu correo para la SEC (obligatorio)

La SEC pide que quien consulta sus datos se identifique con un correo.

1. En tu repositorio, entra a **Settings**, luego **Secrets and variables** y luego **Actions**.
2. Pulsa **New repository secret**.
3. En **Name** escribe `SEC_USER_AGENT`.
4. En **Secret** escribe algo como `La Cinta tu-correo@gmail.com`.
5. Guarda.

## Paso 3: permitir que el robot guarde las alertas

1. Entra a **Settings**, luego **Actions** y luego **General**.
2. Baja hasta **Workflow permissions**.
3. Elige **Read and write permissions** y guarda.

## Paso 4: publicar el sitio

1. Entra a **Settings** y luego **Pages**.
2. En **Source** elige **Deploy from a branch**.
3. Elige la rama `main`, la carpeta `/ (root)` y pulsa **Save**.
4. Espera 1 o 2 minutos. Arriba aparecerá la dirección de tu sitio, por ejemplo `https://tu-usuario.github.io/la-cinta/`.

## Paso 5: la primera actualización

1. Entra a la pestaña **Actions**. Si GitHub pregunta, pulsa el botón para habilitar los workflows.
2. Abre **Actualizar alertas de la SEC**, pulsa **Run workflow** y vuelve a pulsar **Run workflow** en el cuadro que aparece.
3. Espera 1 o 2 minutos hasta que salga la palomita verde.
4. Abre tu sitio: ya tiene alertas reales de los últimos 3 días.

A partir de ahí se actualiza solo, cada 10 minutos de lunes a viernes.

**Para ver el diseño con datos de ejemplo**, agrega `?demo=1` al final de la dirección, por ejemplo `https://tu-usuario.github.io/la-cinta/?demo=1`.

## Opcional: resúmenes con cifras usando IA

Sin IA, cada alerta trae una explicación fija según el tipo de documento. Por ejemplo: "La empresa publicó sus resultados…".

Con IA, la explicación lee el documento real e incluye las cifras: ingresos, ganancia por acción, pronóstico, montos. También escribe titulares concretos, por ejemplo "Nike vendió 10 % menos y retiró su pronóstico" en lugar de "Nike publicó sus resultados". Además marca qué tan relevante es cada noticia, y así los trámites de rutina se esconden.

**Recomendado:** es lo que más mejora la calidad de las noticias.

1. Crea una cuenta en <https://console.anthropic.com> y genera una clave de API.
2. En GitHub, entra a **Settings**, luego **Secrets and variables** y luego **Actions**.
3. Pulsa **New repository secret**, pon el nombre `ANTHROPIC_API_KEY` y pega tu clave.
4. Si quieres elegir el modelo, entra a la pestaña **Variables**, pulsa **New repository variable**, pon el nombre `ANTHROPIC_MODEL` y escribe el modelo. Si no lo configuras, usa `claude-haiku-4-5`, que es el más económico. Revisa en la consola de Anthropic qué modelos están disponibles.

**Cuánto cuesta:** el script resume como máximo 25 documentos por actualización y solo cuando hay documentos nuevos. Con unas 60 empresas, fuera de temporada de resultados, se gastan pocos dólares al mes. Puedes ponerle un límite de gasto en la consola de Anthropic.

## Opcional: canal de Telegram (gratis)

Las alertas importantes se publican solas en un canal de Telegram. Cualquiera puede unirse al canal.

**1. Crear el bot.** En Telegram:

1. Busca **@BotFather**, escríbele `/newbot` y sigue las instrucciones.
2. Al final te da una clave parecida a `123456789:AAH...`. Guárdala.

**2. Crear el canal.**

1. En Telegram, crea un **Nuevo canal** público, por ejemplo con el enlace `t.me/lacinta_alertas`.
2. Entra a la configuración del canal, luego **Administradores** y luego **Agregar administrador**.
3. Busca tu bot, agrégalo y dale permiso para **publicar mensajes**.

**3. Conectarlo en GitHub.** En tu repositorio, entra a **Settings**, luego **Secrets and variables** y luego **Actions**:

1. En la pestaña **Secrets**, pulsa **New repository secret**. Ponle de nombre `TELEGRAM_BOT_TOKEN` y pega la clave del bot.
2. En la pestaña **Variables**, pulsa **New repository variable**. Ponle de nombre `TELEGRAM_CHAT_ID` y escribe `@lacinta_alertas`, o el nombre que le pusiste a tu canal.
3. En la pestaña **Variables**, crea otra variable llamada `SITIO_URL` con la dirección de tu sitio, por ejemplo `https://tu-usuario.github.io/la-cinta`. Así cada mensaje incluye el enlace "Ver en La Cinta".

**Qué se envía:** solo las alertas con relevancia 2 o 3, de las últimas 12 horas, y como máximo 15 por actualización. Los trámites de rutina, como votaciones de accionistas o cambios de estatutos, no se envían.

## Cambiar las empresas que se vigilan

Edita `empresas.txt` desde GitHub con el ícono del lápiz. Pon un símbolo por línea.

Si quieres elegir cómo se muestra el nombre, usa el formato `TICKER | Nombre`, por ejemplo `JPM | JPMorgan Chase`.

Cada empresa agrega una consulta a la SEC por actualización. Hasta unas 300 empresas funciona bien.

## Límites de esta versión gratis (sin sorpresas)

- **Rapidez:** GitHub corre el robot cada 10 minutos, y a veces se atrasa unos minutos más. Para bajar a menos de 1 minuto hace falta un servidor pequeño (unos $5 al mes). En ese servidor el script se corre así:
  `SEC_USER_AGENT="La Cinta tu@correo.com" python3 scripts/sec_alertas.py --loop 60`
- **Pausa automática de GitHub:** GitHub pausa los workflows programados de repositorios sin actividad durante 60 días. Si pasa, vuelve a activarlo en la pestaña **Actions**.
- **Revisión del contenido:** las explicaciones son automáticas y pueden equivocarse. Cada alerta enlaza al documento original de la SEC.
- **Hora de las alertas:** el script toma la hora de aceptación que publica la SEC como hora del Este (ET). Si notas que las horas salen corridas, avísame y lo ajustamos.

## Probarlo en tu computadora (opcional)

Si tienes Python instalado, abre una terminal dentro de la carpeta y corre:

```
python3 -m http.server 8000
```

Luego abre <http://localhost:8000/?demo=1>. Abrir `index.html` con doble clic no funciona, porque el navegador bloquea la carga de las alertas.

## Aviso

La Cinta explica información pública; no es asesoría financiera. Antes de cobrar suscripciones o poner anuncios, consulta con un abogado sobre los avisos legales.
