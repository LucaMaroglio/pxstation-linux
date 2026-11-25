# Verifica su KDE Plasma

L'interfaccia Qt è stata provata su Cinnamon, che però non può simulare alcune cose di KDE.
Questa lista copre proprio quelle. Ogni voce dice cosa fare e cosa ti aspetti di vedere.

## 1. Preparare la VM

- **Distribuzione:** KDE neon (base Ubuntu 24.04 come Mint 22, Plasma 6, sessione Wayland
  predefinita).
- **Risorse:** 2 vCPU, 4 GB di RAM, 25–30 GB di disco. Schermo **SPICE**.
- Nella VM, dopo l'installazione:

  ```bash
  sudo apt install spice-vdagent virt-viewer python3-gi gir1.2-secret-1 gir1.2-notify-0.7 python3-pyqt6
  # su Plasma 5 al posto di python3-pyqt6: python3-pyqt5
  ```
- La VM deve raggiungere l'API di Proxmox (porta 8006) e la porta SPICE/proxy (3128).
- Fai uno **snapshot** prima delle prove, così puoi tornare a uno stato pulito.

## 2. Installare

Copia la cartella del progetto nella VM (per esempio con `scp -r` o `rsync`), poi:

```bash
cd pxstation-linux
./install.sh            # deve dire: Interfaccia per questo desktop: qt
```

Per seguire cosa succede, avvialo da terminale:

```bash
LSC_DEBUG=1 pxstation-linux
```

La prima riga del log deve essere `interface: qt`. La seconda deve indicare la versione di Qt
della sessione e `KDE integration: yes` (Qt 6 su Plasma 6, Qt 5 su Plasma 5).

## 3. Prove — sessione Wayland (predefinita)

Verifica la sessione con `echo $XDG_SESSION_TYPE` → `wayland`.

| # | Cosa fare | Cosa ti aspetti |
|---|---|---|
| 1 | Avvia il programma dal menu applicazioni | Finestra di benvenuto in stile Breeze, con icone |
| 2 | Guarda l'area di notifica (in basso a destra) | Compare l'icona del programma, anche su Wayland |
| 3 | Clic sinistro sull'icona | Si apre la finestra di benvenuto o Macchine virtuali, in primo piano |
| 4 | Menu ☰ → Configura → Proxmox → Aggiungi… con i dati del tuo server | Se il certificato è autofirmato compare l'impronta SHA-256, leggibile per intero |
| 5 | «Considera attendibile» | Il server viene salvato e la lista delle VM si riempie |
| 6 | Apri **KWalletManager** | C'è una voce «PxStation Linux – token API Proxmox» |
| 7 | Se al punto 5 compare «Il portachiavi non è disponibile» | Abilita KWallet in Impostazioni di sistema e riprova. **Annota il caso**: va gestito |
| 8 | Connetti una VM accesa | Si apre remote-viewer; la riga mostra «Sessione: Connessa» |
| 9 | Nella finestra di remote-viewer premi Alt+Tab e il tasto Meta | Annota se vanno alla VM o a Plasma (comportamento di remote-viewer/KWin) |
| 10 | Dalla VM Proxmox «Spegni» la VM dall'interfaccia web | Notifica di Plasma «sessione terminata» con il pulsante **Avvia e riconnetti** |
| 11 | Premi quel pulsante nella notifica | La VM riparte e la sessione si riapre |
| 12 | Interrompi la rete un attimo (per esempio scollega la scheda della VM KDE in Proxmox per 10 s) | Notifica «Connessione persa», poi riconnessione automatica |
| 13 | Clic destro sull'icona → sessione → Alimentazione → Arresta | La VM si arresta, nessuna notifica di errore |
| 14 | Menu ☰ → Apri file… | Si apre la finestra di scelta file **di KDE** |
| 15 | Configura → Generale → «Usa questo programma» | Il testo diventa «I file .vv si aprono con questo programma.» |
| 16 | In Firefox, clicca «SPICE» nell'interfaccia di Proxmox e apri il file | La sessione si apre con il programma e ha alimentazione e riconnessione |
| 17 | Esci dal menu dell'icona con una sessione aperta | Domanda «Chiudere anche le sessioni aperte?» con pulsanti in italiano |
| 18 | Con la finestra coperta da un'altra, clic destro sull'icona del programma nel menu delle applicazioni → «Macchine virtuali» | La finestra già aperta viene in primo piano: non lampeggia soltanto e non si apre una seconda istanza |
| 19 | Con il programma aperto, apri un `.vv` da Dolphin mentre sei in un'altra finestra | La sessione si apre e, se serve, la finestra del programma viene in primo piano |

## 4. Prove — sessione X11 (se disponibile)

Alla schermata di accesso scegli «Plasma (X11)», se presente, e ripeti i punti 1, 2, 3, 8, 9
e 12.

## 5. Cosa mandarmi

- Gli screenshot dei punti 1, 4, 8 e 10 (Spectacle: tasto Stamp).
- L'output del terminale con `LSC_DEBUG=1`, se qualcosa non va.
- Per ogni punto: **OK** oppure cosa hai visto.

Se mi dai accesso SSH alla VM, posso copiare il programma, eseguire i test automatici e fare
gli screenshot io; a te resterebbero solo i clic.
