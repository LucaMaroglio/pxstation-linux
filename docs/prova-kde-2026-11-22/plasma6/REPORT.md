# Versione 0.3: prova su KDE Plasma 6 (Wayland)

## Ambiente

- **VM:** 192.168.0.109, KDE neon User Edition con **Plasma 6.8.1** su **Wayland** (`wayland-1`).
- **Software:** Python 3.12, PyQt6 6.11.0 su Qt 6.11.1, remote-viewer 11.0.
- **Pacchetti:** `virt-viewer`, `python3-pyqt6` e `spice-vdagent` li hai installati tu, perché `sudo`
  chiede la password.
- **Server Proxmox:** era il finto server dei test, sul computer di sviluppo, raggiunto dalla VM
  attraverso un tunnel SSH. Le VM QEMU erano vere ed esponevano SPICE.

**Come ho simulato i clic.** Wayland non permette di simulare mouse e tastiera come xdotool su X11.
Ho quindi usato tre strade:
- per i nostri pulsanti e per quelli di Plasma, l'**accessibilità AT-SPI**, cioè la stessa via di
  un lettore di schermo;
- per il menu dell'icona nell'area di notifica, il **menu D-Bus** esattamente come lo riceve Plasma;
- per le immagini, Spectacle.

Durante le prove l'accessibilità era accesa (`org.a11y.Status IsEnabled`); alla fine l'ho
rimessa com'era (spenta).

## Test automatici

39 test passati. Manca solo la classe che ha bisogno di QEMU, che nella VM non è installato. Sul
computer di sviluppo passano tutti i 45 test.

## Checklist (docs/VERIFICA-KDE.md)

| # | Prova | Esito |
|---|---|---|
| 1 | Avvio dal file `.desktop` (tramite KIO) | **OK.** Log: `Qt 6.11.1 (PyQt6), wayland, KDE integration: yes`. Stile Breeze e icone del tema |
| 2 | Icona nell'area di notifica su Wayland | **OK.** È un StatusNotifierItem con il nome dell'icona del tema; il task manager mostra l'icona giusta (app_id) |
| 3 | Clic sull'icona mentre Dolphin è in primo piano | **OK.** Plasma manda `ProvideXdgActivationToken` e poi `Activate`, e la finestra Macchine virtuali diventa attiva |
| 4 | Aggiunta del server con certificato autofirmato | **OK.** Impronta SHA-256 leggibile per intero |
| 5 | «Considera attendibile» | **OK.** Il server viene salvato e la lista mostra i 3 stati |
| 6 | Segreto nel portachiavi | **OK, ma in GNOME Keyring.** Su questa VM il servizio Secret Service è di gnome-keyring, installato dal 25/10, e non di ksecretd (KWallet). Il programma usa correttamente quello attivo |
| 7 | Portachiavi non disponibile | Non verificabile: qui era disponibile |
| 8 | Connetti | **OK.** remote-viewer gira nativo su Wayland e la sua finestra è attiva |
| 9 | Alt+Tab / Meta dentro remote-viewer | **Da provare a mano.** Su Wayland non si possono simulare i tasti |
| 10 | VM spenta dall'esterno | **OK.** Notifica di Plasma con il nome del programma, la sua icona e il pulsante; dopo 15 s è ancora visibile |
| 11 | «Avvia e riconnetti» nella notifica | **OK.** La VM riparte e la sessione si riapre |
| 12 | Caduta della connessione | **OK.** Riconnessione automatica con un ticket nuovo |
| 13 | Icona › sessione › Alimentazione › Arresta | **OK.** Il menu ricevuto da Plasma è corretto, la VM si arresta e non compaiono errori |
| 14 | «Apri file…» | **OK.** Finestra di KDE; il file scelto si apre |
| 15 | Preferenze › Generale | **OK.** Testi completi; il programma risulta già predefinito per i `.vv` |
| 16 | `.vv` aperto da Plasma (`kde-open`) | **OK.** Lo apre il nostro programma (l'istanza già aperta) |
| 17 | Esci con una sessione aperta | **OK.** La domanda compare in primo piano; dopo «Chiudi sessioni» non resta nulla aperto e la cartella temporanea è vuota |
| 18 | Azione rapida con la finestra coperta | **In parte.** Il token arriva all'istanza aperta (verificato dal log). Che KWin lo accetti va provato a mano: serve un clic vero nel menu |
| 19 | `.vv` da Dolphin mentre sei su un'altra finestra | **In parte, dopo una correzione (sotto).** Il token arriva fino a remote-viewer. Il primo piano va provato a mano |

## Correzioni fatte durante la prova

**Token di attivazione perso con i file `.vv` (punto 19).**
- **Problema:** quando un secondo avvio passava un `.vv` all'istanza già aperta, il token non
  arrivava. Gio.Application, a differenza della versione GTK, non lo aggiunge da sola alla
  richiesta. In più, anche quando arrivava, restava al nostro programma, mentre la finestra da
  portare in primo piano è quella di remote-viewer.
- **Correzione:** il secondo avvio ora allega il token alla richiesta. remote-viewer lo eredita al
  lancio della sessione e poi il programma lo scarta, così un lancio successivo non lo riusa.
- **Verifica sulla VM:** il token arriva nell'ambiente di remote-viewer, e al lancio seguente non c'è più.

**Interfaccia GTK.** Avevo provato ad aggiungere lo stesso passaggio anche lì. Chiamato fuori dal
flusso reale, però, il codice faceva andare in crash Python, e non potevo provarlo in modo sicuro
con la tua copia installata aperta. L'ho tolto. Su Cinnamon (X11) il beneficio sarebbe minimo.

## Osservazioni

- **KWallet.** Su questa VM gnome-keyring occupa il servizio Secret Service prima di KWallet.
  Per provare KWallet bisognerebbe disinstallare gnome-keyring o disattivarlo: non l'ho fatto,
  perché è una modifica al sistema.
- **Menu Alimentazione dell'icona.** Mostra tutte le azioni anche quando non servono (per esempio
  «Riprendi» con la VM accesa), perché la sessione non conosce lo stato di pausa. Era così anche
  prima; Proxmox ignora l'azione inutile.

## Da provare a mano (pochi minuti)

1. **Punto 9:** in remote-viewer premi Alt+Tab e il tasto Meta.
2. **Punto 18:** copri la finestra del programma, poi clic destro sull'icona nel task manager ›
   «Macchine virtuali». Deve venire in primo piano.
3. **Punto 19:** con Dolphin in primo piano, doppio clic su un `.vv`. La finestra di remote-viewer
   deve comparire davanti.
