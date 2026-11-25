<p align="center"><img src="docs/PxStationLogo.png" width="128" height="128" alt="PxStation Linux"></p>

# PxStation Linux

> **PxStation Linux è un fork del porting per Linux di
> [macos-spice-client](https://github.com/pawelwiecaszek/macos-spice-client)** di Paweł Więcaszek
> (licenza MIT), rinominato e mantenuto da Luca Maroglio. Fa parte della famiglia PxStation insieme a
> [PxStation Mac](https://github.com/LucaMaroglio/pxstation-mac) e
> [PxStation Windows](https://github.com/LucaMaroglio/pxstation-win).

Le macchine virtuali **Proxmox VE** sulla scrivania Linux: elenco delle VM, accensione e
spegnimento, connessione con un clic e **riconnessione automatica con un ticket nuovo**. Lo
schermo della VM è mostrato da `remote-viewer` (virt-viewer).

Un unico programma con **due interfacce**: **GTK** per **Cinnamon** (Linux Mint) e **Qt** per
**KDE Plasma**. Al primo avvio sceglie da solo quella adatta al desktop.

È la versione per Linux di [macos-spice-client](https://github.com/pawelwiecaszek/macos-spice-client),
di cui riprende l'interfaccia e la logica Proxmox. Il protocollo SPICE, invece di essere
riscritto, è delegato a `remote-viewer`.

## Funzioni

**Macchine virtuali** (finestra principale)
- Le VM di tutti i server Proxmox configurati, con lo stato (in esecuzione, in pausa, spenta)
  aggiornato ogni 10 secondi (Ctrl+R per aggiornare subito).
- **Connetti**, **Riprendi e connetti** o **Avvia e connetti**: il programma avvia la VM se serve,
  chiede a Proxmox un ticket SPICE nuovo e apre remote-viewer.
- Menu **Alimentazione** (pulsante ⏻ o clic destro): Arresta, Riavvia, Metti in pausa, Riprendi,
  Reset… e Spegni forzatamente… Le ultime due chiedono conferma.

**Sessioni**
- **Riconnessione automatica** quando la connessione cade: ogni tentativo usa un ticket nuovo
  ottenuto dall'API. I tentativi sono 8, con attese crescenti (1 → 30 s), e la riconnessione
  aspetta che torni la rete.
- Se chiudi tu la finestra non c'è riconnessione, e nemmeno quando arresti la VM dal programma.
- Se la VM risulta spenta, la notifica e il menu offrono **Avvia e riconnetti**.
- **Icona nell'area di notifica** con le sessioni aperte. Per ognuna ci sono il menu di
  alimentazione, Riprova ora, Annulla riconnessione e Disconnetti.

**File `.vv`**: puoi aprire anche quelli scaricati dal pulsante SPICE di Proxmox. In
Preferenze › Generale puoi rendere il programma l'applicazione predefinita per i `.vv`.

**Sicurezza**
- Certificato verificato dal sistema o dalla CA del cluster, oppure considerato attendibile
  dopo il confronto dell'impronta SHA-256. La verifica non si può disattivare.
- I segreti dei token API stanno nel portachiavi: GNOME Keyring su Cinnamon, KWallet su KDE.
- I file di connessione temporanei sono privati e vengono cancellati subito.

## Le due interfacce

| | Cinnamon | KDE Plasma 5 (X11) | KDE Plasma 6 (Wayland o X11) |
|---|---|---|---|
| Interfaccia | GTK 3 | Qt 5 (PyQt5) | Qt 6 (PyQt6) |
| Icona nell'area di notifica | XApp (applet di Cinnamon) | StatusNotifierItem | StatusNotifierItem |
| Portachiavi | GNOME Keyring | KWallet o GNOME Keyring (Secret Service) | KWallet, oppure GNOME Keyring se installato (Secret Service) |
| Finestre | Barra del titolo integrata, interruttori | Barra degli strumenti, schede, caselle di spunta | come Plasma 5 |

La scelta è automatica: `XDG_CURRENT_DESKTOP` contiene `KDE` → Qt, altrimenti GTK. Per forzare
una delle due: `LSC_UI=gtk` oppure `LSC_UI=qt`.

**Qt 5 o Qt 6.** Plasma integra solo la versione di Qt della propria sessione: Qt 5 su Plasma 5,
Qt 6 su Plasma 6. Solo con quella il programma ha lo stile Breeze, il tema di icone scelto e le
finestre di dialogo di KDE. Il programma la sceglie da `KDE_SESSION_VERSION`; per forzarla:
`LSC_QT=5` oppure `LSC_QT=6`. Se manca, usa l'altra versione e lo segnala. In quel caso legge
comunque il tema di icone di Plasma e apre i file con la finestra di KDE tramite il portale
(xdg-desktop-portal-kde), ma lo stile resta quello generico di Qt.

**Integrazione con Plasma 6 su Wayland**
- Le finestre portano l'id del file `.desktop` (app_id): icona e voce nel task manager corrette.
- Quando un `.vv` arriva dal browser, oppure si riavvia il programma o si usa un'azione rapida,
  la richiesta passa all'istanza già aperta insieme al suo token di attivazione (xdg-activation).
  Così KWin porta davvero in primo piano la finestra giusta (la finestra del programma oppure, per
  un `.vv`, quella di remote-viewer) invece di farla solo lampeggiare.
- Le azioni rapide del file `.desktop` (Macchine virtuali, Apri file di connessione…, Preferenze)
  compaiono nel menu delle applicazioni e nel task manager.
- Le notifiche sono associate al programma (`desktop-entry`). Quelle con un pulsante (per esempio
  «Avvia e riconnetti») restano finché le usi o finché la sessione cambia stato; prima, invece,
  Plasma le chiudeva dopo pochi secondi e il pulsante smetteva di funzionare.

## Requisiti

Tutto è nei repository di Linux Mint 22, Ubuntu 24.04, Kubuntu e KDE neon:

```bash
# comuni
sudo apt install virt-viewer python3-gi gir1.2-secret-1 gir1.2-notify-0.7
# Cinnamon
sudo apt install gir1.2-gtk-3.0 gir1.2-xapp-1.0
# KDE Plasma 6
sudo apt install python3-pyqt6
# KDE Plasma 5
sudo apt install python3-pyqt5
```

`install.sh` controlla quelli necessari per il desktop in uso e indica cosa manca.

## Installazione

Senza permessi di amministratore, solo per il tuo utente:

```bash
./install.sh
```

Vengono installate sempre entrambe le interfacce; quella usata dipende dal desktop
all'avvio. Per disinstallare: `./uninstall.sh` (con `--purge` elimini anche impostazioni e
token).

## Configurare Proxmox

1. In Proxmox crea un token API: **Datacenter › Permissions › API Tokens**. Il token deve avere
   **VM.Audit**, **VM.PowerMgmt** e **VM.Console**, per esempio il ruolo *PVEVMUser* su `/vms`.
2. Nel programma apri **Preferenze › Proxmox › Aggiungi** e inserisci host, porta (8006), ID
   del token (`utente@pve!nome`) e segreto.
3. Se il certificato è autofirmato, confronta la sua impronta SHA-256 con quella in
   **Proxmox › nodo › System › Certificates** prima di accettarla.

Nelle VM: schermo **SPICE** e **spice-vdagent** (Linux) o **SPICE guest tools** (Windows).

## Struttura del codice

```
linux_spice_client/
  main.py      sceglie l'interfaccia per il desktop
  core/        tutto ciò che è condiviso, senza codice grafico:
               API Proxmox e TLS, sessioni remote-viewer e riconnessione, impostazioni,
               portachiavi, notifiche, contenuto dei menu, testi
               (controller.py è il punto d'incontro con le interfacce)
  gtk/         interfaccia GTK 3 (Cinnamon)
  qt/          interfaccia Qt (KDE Plasma): binding.py sceglie PyQt5 o PyQt6
```

Le interfacce si limitano a disegnare. Azioni, testi e voci dei menu arrivano da `core`, così
le due versioni si comportano allo stesso modo e una correzione vale per entrambe. Un test
verifica che `core` non importi né GTK né Qt.

Qt su Linux usa il ciclo di eventi di GLib, quindi il nucleo (timer, processi, D-Bus via
Gio) funziona uguale sotto entrambe le interfacce. Anche l'istanza unica e il passaggio dei
file `.vv` usano lo stesso nome D-Bus.

## Come riconosce le cadute di connessione

remote-viewer viene avviato con `G_MESSAGES_DEBUG=virt-viewer` e il suo output finisce in un
file privato. Dall'ordine dei messaggi si distingue:

- **caduta lato server**: `main channel: closed` arriva prima dello smontaggio dei canali;
- **chiusura da parte tua**: remote-viewer smonta prima i canali (`zap main channel`);
- **errore di connessione** o di autenticazione, prima che la sessione si apra.

La logica è stata verificata con remote-viewer 11.0.

## Sviluppo

```bash
python3 -m unittest discover -s tests -t . -v                     # test
python3 tests/fake_proxmox.py --port 18006                       # finto Proxmox
LSC_UI=qt LSC_QT=5 LSC_DEBUG=1 XDG_CONFIG_HOME=/tmp/lsc ./bin/pxstation-linux
```

Attenzione: il programma è a istanza unica (nome D-Bus `org.linuxspiceclient.LinuxSpiceClient`).
Se la copia installata è in esecuzione, una copia di sviluppo avviata nella stessa sessione le
passa le richieste invece di partire. Prima di provare, chiudi la copia installata.

`tests/fake_proxmox.py` simula l'API (token `test@pve!spice`, segreto
`11111111-2222-3333-4444-555555555555`) con vere VM QEMU che espongono SPICE. Con
`GET /test/drop/<vmid>` simula una caduta della connessione.

Per provare su KDE segui [docs/VERIFICA-KDE.md](docs/VERIFICA-KDE.md).

## Lingua dell'interfaccia

L'interfaccia è in **inglese** e **italiano** (stesse regole di PxStation Mac). In
**Preferenze › Generale › Lingua** si sceglie la lingua oppure «Predefinita di sistema»: in quel caso
vale la prima lingua supportata fra `LANGUAGE`, `LC_ALL`, `LC_MESSAGES` e `LANG`, e se nessuna è
supportata si usa l'inglese. Il cambio vale dal riavvio successivo del programma.

I testi nel codice sono in inglese e passano da `_()` (`linux_spice_client/core/i18n.py`); le
traduzioni stanno in `data/locale/<lingua>.json`. Per aggiungere una lingua basta un nuovo file
con le stesse chiavi di `it.json`: compare da solo nelle preferenze. `tests/test_i18n.py` verifica
che il catalogo italiano contenga tutti i testi.

## Novità di PxStation Linux 0.3.1

- Nuovo nome (PxStation Linux), icona e logo; box Informazioni con nome, versione e «2026 - Luca Maroglio».
- Interfaccia in inglese e italiano con scelta della lingua nelle preferenze.
- Le impostazioni della versione precedente (`~/.config/linux-spice-client`) vengono copiate al primo
  avvio; i token restano nel portachiavi. La vecchia installazione (`~/.local/share/linux-spice-client`)
  va rimossa con l'`uninstall.sh` della versione precedente.

## Licenza

MIT. Interfaccia, logica Proxmox e icona originale derivano da macos-spice-client © Paweł Więcaszek
(MIT): vedi `NOTICE`. Modifiche di PxStation Linux © 2026 Luca Maroglio.
