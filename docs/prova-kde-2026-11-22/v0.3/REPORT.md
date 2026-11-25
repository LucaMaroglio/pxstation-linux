# Versione 0.3: prova su KDE Plasma 5 (X11)

- **VM:** 192.168.0.128, Linux Mint 22.3 con Plasma 5.27 su X11. È la stessa della prova precedente.
- **Prova:** sono stati provati sia l'uso normale con Qt 5 sia il ripiego che usa Qt 6 forzato.
- **Mancante:** Plasma 6 su Wayland non era disponibile, quindi va ancora provato (vedi in fondo).

## Cosa cambia nella 0.3

| Area | Prima (0.2) | Ora (0.3) |
|---|---|---|
| Versione di Qt | Sempre Qt 6 | Quella della sessione: Qt 5 su Plasma 5, Qt 6 su Plasma 6 (`LSC_QT` per forzarla) |
| Stile, colori, icone su Plasma 5 | Fusion chiaro, senza icone | Quelli scelti in Plasma (qui tema scuro e icone BlackSur) |
| «Apri file…» su Plasma 5 | Finestra generica di Qt | Finestra di KDE |
| Ripiego (manca il Qt della sessione) | — | Finestra di KDE tramite portale, tema di icone letto da kdeglobals |
| Preferenze › Generale | Note tagliate | Note complete; la pagina scorre se la finestra è piccola |
| Notifiche con pulsante | Chiuse da Plasma dopo circa 10 s | Restano finché le usi, si chiudono da sole quando la sessione riparte |
| Log di remote-viewer all'uscita | Rimaneva un file | Cancellato |
| Testi secondari su tema scuro | Invisibili con Qt 5 | Leggibili; si aggiornano se cambi schema di colori |
| Benvenuto | Restava aperto dietro la lista | Si chiude quando si apre la lista delle VM (GTK e Qt) |
| Azioni rapide nel menu | — | Macchine virtuali, Apri file di connessione…, Preferenze |
| Wayland | Solo app_id | Il token di attivazione passa all'istanza già aperta, così KWin porta la finestra in primo piano |
| Installazione | Chiedeva sempre PyQt6 | Chiede PyQt5 o PyQt6 secondo la sessione, più il motore di icone SVG di Qt |

## Prove eseguite sulla VM

| Prova | Esito |
|---|---|
| `install.sh` con Plasma 5 | **OK.** Indica «qt (Qt 5)» |
| Avvio | **OK.** Log: `Qt 5.15.13 (PyQt5), xcb, KDE integration: yes` |
| Benvenuto, lista VM, aggiunta del server con certificato autofirmato | **OK.** Colori e icone del tema di Plasma |
| «Apri file…» | **OK.** Finestra di KDE |
| Preferenze › Generale | **OK.** Nessun testo tagliato |
| Azioni `--action=preferences` e `--action=vm-list` con il programma già aperto | **OK.** Le esegue l'istanza aperta |
| VM spenta dall'esterno | **OK.** La notifica è ancora visibile dopo 20 s |
| VM riavviata dalla lista | **OK.** La notifica si chiude da sola |
| Pulsante «Avvia e riconnetti» premuto dopo 15 s | **OK.** La sessione riparte |
| Caduta della connessione | **OK.** Riconnessione automatica |
| `--action=quit` con una sessione aperta | **OK.** Compare la domanda; la prima versione andava in timeout, corretto |
| «Lascia aperte» | **OK.** Il programma esce, remote-viewer resta aperto, la cartella temporanea è vuota |
| Ripiego con `LSC_QT=6` | **OK.** «Apri file…» usa il portale (finestra KDE) e il file scelto si apre |
| Ripiego con `LSC_QT=6`: icone | Mancano, perché sulla VM non c'è `libqt6svg6`. Ora `install.sh` lo chiede e il programma lo segnala nel log |

## Test automatici

Sul computer di sviluppo passano tutti i 45 test. Sulla VM ne passano 39; manca solo la classe
che ha bisogno di QEMU, che non è installato.

## Ancora da provare su Plasma 6 / Wayland

Servono i punti 1–19 di [VERIFICA-KDE.md](../../VERIFICA-KDE.md), in particolare questi:

- **18–19 (primo piano su Wayland):** l'azione rapida o un `.vv` aperto da Dolphin portano in
  primo piano la finestra già aperta.
- **3 (clic sinistro sull'icona su Wayland):** la finestra viene in primo piano anche qui.
  Questo dipende da come Qt gestisce il token di attivazione dell'area di notifica.
- **KWallet** come Secret Service.
