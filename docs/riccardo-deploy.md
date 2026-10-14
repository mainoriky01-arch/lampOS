# Riccardo's deploy guide — fork personale OrangePi 4 Pro

Questo documento descrive la procedura end-to-end per costruire l'immagine,
flashare la microSD, fare il primo avvio e gli aggiornamenti successivi dal
Mac via SSH. Nessun passaggio richiede servizi cloud Autonomous.

## 0. Prerequisiti sul Mac

- Docker Desktop installato e avviato (serve per la build dell'immagine).
- ≥ 4 GB RAM assegnata a Docker, ≥ 30 GB di spazio libero su disco.
- `go` (per cross-compilare `os-server` nei deploy incrementali — già installato
  su questo Mac).
- Una microSD da flashare + lettore SD/USB.

## 1. Build dell'immagine golden (Docker)

Dalla root del repo:

```bash
cd scripts/imager
make build TARGET=opi DEVICE_TYPE=lamp OTA_METADATA_URL=https://riccardo.example/ota/metadata.json
```

Note:
- `OTA_METADATA_URL` è **obbligatorio** anche se non verrà mai usato per OTA
  reali in questa build — la build fallisce in preflight senza. Usa un
  placeholder valido come URL sintatticamente (es. un file statico che potresti
  ospitare su GitHub Pages in futuro) o un segnaposto come
  `https://localhost/metadata.json` se non hai ancora un hosting: l'immagine si
  costruisce comunque, l'URL viene solo scritto dentro `/root/config/bootstrap.json`
  e non viene contattato finché non attivi un aggiornamento OTA reale.
- `DEVICE_TYPE=lamp` seleziona il profilo hardware/persona della lampada
  (`robots/lamp/`). Finché non create un profilo `robots/lampos/` dedicato,
  usate `lamp`.
- Prima build: ~25-40 minuti (scarica base image, compila os-server, HAL, web UI).
- Build successive: più veloci grazie alla cache Docker, a meno che
  `build-orangepi.sh` sia cambiato (il target `build` invalida sempre l'immagine
  `pi-builder` per evitare bug di cache stantia).
- Output: `scripts/imager/output/lamp/golden-opi-lamp.img.xz`.

## 2. Flash della microSD

```bash
cd scripts/imager
make sd-card-list              # trova il numero disco della SD (es. disk4)
make sd-card-flash DEVICE_TYPE=lamp DISK=<N>
```

`sd-card-flash` scrive l'immagine `.xz` del passo 1. Per un giro più rapido
durante lo sviluppo (senza aspettare la ri-compressione xz), usa
`make sd-card-flash-raw DEVICE_TYPE=lamp DISK=<N>` sul `.img` grezzo, se
disponibile (serve `COMPRESS=0` nella build precedente).

**Attenzione**: `DISK` deve essere il numero del disco corretto — un numero
sbagliato sovrascrive il disco di sistema. Usa sempre `sd-card-list` prima e
verifica dimensione/nome del disco target.

## 3. Primo avvio

1. Inserisci la microSD nell'OrangePi 4 Pro e accendi.
2. La board entra in modalità Access Point: cerca una rete WiFi `lamp-xxxx` dal
   tuo Mac/telefono e connettiti.
3. Apri `http://192.168.100.1/` nel browser — pagina di setup WiFi.
4. Inserisci le credenziali della tua rete WiFi di casa. La board si riavvia e
   passa in modalità client (STA), connessa alla tua LAN.
5. Trova l'IP assegnato dal router (DHCP lease, o `arp -a` / app del router).

## 4. Primo deploy della config personale

Con la board raggiungibile via SSH sulla LAN (utente/password default
`orangepi`/`orangepi` finché non li cambi):

```bash
ssh orangepi@<IP_BOARD> mkdir -p /root/config
scp config/config.riccardo.json orangepi@<IP_BOARD>:/root/config/config.json
ssh orangepi@<IP_BOARD> systemctl restart os-server hal
```

Prima di questo passo, compila i campi segnaposto in
`config/config.riccardo.json` (vedi CLAUDE.md, sezione "Fields to fill in
manually"): `llm_model`, `admin_password_hash`, `session_secret`,
`network_ssid`/`network_password` se non già impostati via captive portal.

## 5. Sviluppo quotidiano — deploy incrementale dal Mac via SSH

Non serve ricostruire l'immagine né usare OTA per ogni modifica. Dalla root
del repo:

```bash
IP=<IP_BOARD> make hal-deploy      # rsync del codice HAL Python + restart hal.service (no build)
IP=<IP_BOARD> make os-deploy       # cross-compile os-server (GOOS=linux GOARCH=arm64) + swap binario
IP=<IP_BOARD> make device-deploy   # entrambi insieme
IP=<IP_BOARD> make hal-log         # tail del log HAL in tempo reale (FOLLOW=1 di default)
IP=<IP_BOARD> make os-log          # tail del log os-server
```

Variabili utili:
- `J=<jump-host>` — se la board non è direttamente raggiungibile, instrada
  ssh/scp/rsync attraverso un host ponte.
- `PI_USER` (default `orangepi`), `PI_PASS` (default `orangepi`; passa
  `PI_PASS=""` per usare solo la chiave SSH).
- `GREP='<regex>'` con `hal-log`/`os-log` per filtrare i log lato board prima
  che arrivino sul Mac.

`hal-log`/`os-log` non deployano nulla — sicuri da lanciare mentre la lampada
è in uso.

## 6. Nessun OTA cloud necessario

Questa build non usa mai il canale OTA reale di Autonomous (`upload-*`/
`promote-*` target del Makefile principale restano inutilizzati). Tutti gli
aggiornamenti durante lo sviluppo passano da SSH diretto (punto 5). L'OTA
reale (bootstrap-server che tira aggiornamenti da `OTA_METADATA_URL`) resta
un'opzione futura se vorrai un canale di aggiornamento automatico, non
necessaria per l'uso quotidiano.

## Checklist rapida

- [ ] Docker installato e avviato
- [ ] `make build TARGET=opi DEVICE_TYPE=lamp OTA_METADATA_URL=...` completato
- [ ] microSD flashata con `make sd-card-flash`
- [ ] Primo avvio: WiFi configurato via `192.168.100.1`
- [ ] IP della board trovato
- [ ] `config.riccardo.json` compilato (campi manuali) e copiato su `/root/config/config.json`
- [ ] `make hal-deploy` / `make os-deploy` testati con una modifica di prova
