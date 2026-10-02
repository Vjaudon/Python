# ASN Wave Monitor

Application de suivi des vagues à partir du heave mesuré. Elle estime la hauteur significative `Hs` et la période de pic `Tp`, affiche les mesures de vent et de courant, signale l'état des capteurs et enregistre les données au format CSV.

## Fonctionnalités

- Acquisition par UDP ou port série, ou génération de données en mode simulation avec affichage des valeurs et courbes de vagues, vent et courant; la correction RAO du navire n'est pas appliquée aux vagues simulées.
- Configuration des ports UDP et série par équipement dans l'onglet **Ports**. L'IP source UDP est facultative; lorsqu'elle est renseignée, seuls les datagrammes provenant de cette IPv4 sont acceptés.
- Décodage du heave Octans au format `$PHLIN,x.xxx,y.yyy,z.zzz*hh`, avec vérification du checksum XOR et gestion des trames série fragmentées.
- Calcul spectral sur une fenêtre glissante de 20 minutes, avec detrend et méthode de Welch.
- Correction du spectre par la RAO du navire et de la direction sélectionnés.
- Affichage de `Hs`, `Tp`, du vent, du courant, des alertes, de l'état de réception et de l'historique.
- Graphiques d'évolution de `Hs`/`Tp` et du vent/courant dans l'onglet **Graphiques**.
- Enregistrement horodaté des mesures et des erreurs dans des fichiers CSV sous `data/`.
- Consultation des fichiers enregistrés dans l'onglet **Données**, avec aperçu et ouverture de l'historique complet.

## Installation et lancement

Python 3.8 ou ultérieur est recommandé. Tkinter doit être disponible avec l'installation Python.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Installateur Windows

Pour générer `dist/ASN-Wave-Monitor-Setup-v3.0.0.exe`, installez les dépendances du projet, PyInstaller (`py -m pip install --user pyinstaller`) et Inno Setup 6, puis exécutez :

```powershell
.\build_installer.ps1
```

L'installateur configure l'application dans `%LOCALAPPDATA%\Programs\ASN Wave Monitor`, inclut les classeurs RAO et crée un raccourci dans le menu Démarrer. La configuration et les journaux sont conservés lors d'une désinstallation ou d'une mise à jour.

Le fichier `config.json` fourni démarre en mode UDP. Pour essayer l'interface sans capteurs, régler `inputs.mode` à `simulation`. Le profil de mer utilisé en simulation est défini par `inputs.preset` (`calm`, `moderate`, `rough` ou `instrument`).

## Acquisition

Les transports, hôtes et ports sont définis dans `config.json`. La configuration fournie utilise UDP : Octans sur le port 9998, courant sur 5001 et vent sur 5002. Les hôtes et ports doivent correspondre à l'installation du bord. Le mode série est également disponible pour le flux PHLIN Octans.

Le calcul utilise une fréquence d'échantillonnage configurée actuellement à 5 Hz et limite l'analyse à la bande 0,03-0,5 Hz. Vérifier ces paramètres avec les données et les capteurs réellement utilisés.

## Profils navire et RAO

Le menu **Navire** choisit le profil RAO. Le menu **Direction de houle** choisit l'incidence relative au navire. Les profils disponibles sont **IOT - Ile d'Ouessant** et **IME - Ile de Molène**; l'IOT reste sélectionné au démarrage. Leur direction initiale est de 0°.

Le classeur Excel IOT comporte des onglets nommés par angle. Le lecteur prend la période en secondes de la colonne B et l'amplitude HEAVE de la colonne E. Le classeur Molène utilise des onglets suffixés par `°`, avec la période en colonne A et l'amplitude HEAVE en colonne F. Dans les deux cas, la période est convertie en fréquence (`f = 1 / T`), puis les gains sont interpolés selon l'angle sélectionné. Hors de la plage de fréquences couverte, le gain est neutre (1), donc aucune correction RAO n'est appliquée.

La correction est appliquée au spectre avant le calcul des deux indicateurs :

```text
PSD_corrigee(f) = PSD_heave(f) / RAO(f)^2
Hs = 4 * sqrt(integrale(PSD_corrigee))
Tp = 1 / frequence_du_pic(PSD_corrigee)
```

Les classeurs IOT et Molène sont fournis dans `rao/` et référencés par des chemins relatifs dans `config.json`. Copier le dossier complet de l'application conserve ainsi les RAO avec elle. Pour ajouter un navire, placer son classeur dans `rao/` et ajouter une entrée dans `vessels` avec son chemin relatif et `default_heading_deg`.

## Données et validation

Chaque lancement crée un fichier `.csv` horodaté dans `data/`. Les lignes sont identifiées comme `measurement` ou `error`; les en-têtes décrivent les colonnes et les erreurs partagent le journal des mesures. Les anciens fichiers `.txt` restent consultables dans l'onglet **Données**. Ces journaux facilitent l'analyse, mais ne constituent pas à eux seuls une validation métrologique.

Avant tout usage opérationnel, valider les conventions de direction, les paramètres d'acquisition, les courbes RAO, le calcul de `Hs` et de `Tp` avec des données réelles et une référence indépendante. Le classeur IOT fourni correspond à la condition « arrival from test to concrete », à vitesse nulle et en profondeur d'eau infinie ; vérifier que ces hypothèses correspondent à la situation d'utilisation.
