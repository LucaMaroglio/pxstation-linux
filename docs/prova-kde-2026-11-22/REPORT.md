# Prova su KDE Plasma — 22/11/2026

## Ambiente

- **VM:** 192.168.0.128, Linux Mint 22.3. **KDE Plasma 5.27.12** su **X11**. Non è KDE neon/Plasma 6
  come prevedeva la checklist.
- **Sessione Wayland:** non installata, quindi le prove su Wayland non sono state fatte.
- **Portachiavi:** il servizio Secret Service è fornito da **gnome-keyring** (eredità di Mint), non da KWallet.
- **Software:** Python 3.12, PyQt6 6.6.1 su Qt 6.4.2, remote-viewer 11.0.
- **Server Proxmox:** era il finto server dei test, sul mio computer, raggiunto dalla VM attraverso un
  tunnel SSH. Le VM QEMU erano vere ed esponevano SPICE.
- **Automazione:** nessun intervento manuale. I clic sono stati simulati con xdotool, preso dai
  repository e scaricato in una cartella temporanea poi cancellata. Gli screenshot sono di Spectacle.

## Test automatici

29 test su 30 superati. L'unico mancante, la classe FakeServerTests, ha bisogno di
`qemu-system-x86_64`, che non è installato nella VM. Sul computer di sviluppo passano tutti e 35.

## Checklist

| # | Prova | Esito |
|---|---|---|
| 1 | Avvio, finestra di benvenuto | **OK.** Interfaccia `qt` scelta da sola. Stile Fusion, non Breeze (vedi problema A) |
| 2 | Icona nell'area di notifica | **OK.** Menu reso da Plasma (SNI/dbusmenu) |
| 3 | Clic sinistro sull'icona | **OK.** La finestra torna in primo piano |
| 4 | Aggiungi server, certificato autofirmato | **OK.** L'impronta SHA-256 si legge per intero |
| 5 | «Considera attendibile» | **OK.** Il server viene salvato e la lista mostra i 3 stati corretti |
| 6 | Segreto nel portachiavi | **OK.** Voce «Linux Spice Client – token API Proxmox» nella raccolta Login di gnome-keyring |
| 7 | Portachiavi non disponibile | Non verificabile: il portachiavi qui era disponibile |
| 8 | Connetti | **OK.** remote-viewer si apre e la riga mostra «Disconnetti» |
| 9 | Alt+Tab / Meta dentro remote-viewer | Alt+Tab va alla VM. **Meta apre il menu di Plasma** (comportamento di KWin/remote-viewer) |
| 10 | VM spenta dall'esterno | **OK.** Notifica «sessione terminata» con «Avvia e riconnetti» |
| 11 | Pulsante della notifica | **OK** se premuto entro circa 10 s (vedi problema C) |
| 12 | Caduta della connessione | **OK.** Riconnessione in meno di 2 s con un ticket nuovo e notifica «Riconnessa» |
| 13 | Icona › sessione › Alimentazione › Arresta | **OK.** La VM si arresta senza notifiche di errore |
| 14 | Apri file… | **NON OK.** Si apre la finestra di Qt, non quella di KDE (problema A) |
| 15 | Associazione dei `.vv` | **OK.** Già predefinita dopo `install.sh`, il testo è corretto. Le note sono tagliate (problema B) |
| 16 | Aprire un `.vv` come dal browser | **OK.** `xdg-open` lo passa all'istanza già aperta, che avvia la sessione |
| 17 | Esci con una sessione aperta | **OK.** Domanda in italiano; «Chiudi sessioni» chiude tutto |

## Problemi trovati

**A. Qt 6 su Plasma 5 non ha l'integrazione KDE (il più importante).**
Plasma 5 integra solo Qt 5: per Qt 6 ci sono il solo tema GTK e nessuno stile Breeze. Il programma
quindi appare con lo stile Fusion e senza icone del tema (si vedono i testi di riserva), e
«Apri file…» usa la finestra generica di Qt. Su Plasma 6 (KDE neon, Kubuntu 24.10 o successive) il
problema non dovrebbe presentarsi. Soluzioni possibili:

1. Su Plasma 5 usare PyQt5, che è perfettamente integrato. Le differenze con PyQt6 nel nostro codice
   sono poche.
2. Restare su Qt 6 e:
   - aprire i file con il portale (`org.freedesktop.portal.FileChooser`, che qui c'è ed è quello di KDE);
   - leggere il tema di icone da `~/.config/kdeglobals`.

   Lo stile resterebbe Fusion.
3. Supportare ufficialmente solo Plasma 6.

**B. Preferenze › Generale: note tagliate.**
Con i caratteri di Plasma le note su più righe non hanno abbastanza altezza e l'ultima riga è
tagliata. La correzione è semplice: dimensioni minime corrette oppure un'area scorrevole.

**C. Le azioni nelle notifiche durano circa 10 s.**
Allo scadere del popup Plasma chiude la notifica (NotificationClosed, motivo 1 = scaduta) e il
pulsante «Avvia e riconnetti» non è più utilizzabile. L'azione resta disponibile dal menu
dell'icona e dalla finestra. Correzione possibile: rendere persistenti (`resident` / senza scadenza)
le notifiche che hanno un'azione.

**D. Minore: un file di log rimasto.**
Dopo «Chiudi sessioni» resta in `$XDG_RUNTIME_DIR/linux-spice-client` il log di remote-viewer
dell'ultima sessione. Riguarda il nucleo, quindi anche Cinnamon. È una cartella privata in RAM,
quindi il danno è nullo.

## Stato della VM dopo le prove

- **Restano:** il programma installato in `~/.local` e i sorgenti in `~/linux-spice-client`.
- **Rimossi:** server di prova, segreto nel portachiavi, impostazioni, file temporanei e xdotool.
