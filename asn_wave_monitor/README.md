# ASN Wave Monitor

Application de suivi des vagues à partir du heave mesuré. Elle estime la hauteur significative `Hs` et la période de pic `Tp`, affiche les mesures de vent et de courant, signale l'état des capteurs et enregistre les données dans une base SQLite.

## Fonctionnalités

- Acquisition par UDP ou port série, ou génération de données en mode simulation.
- Décodage du heave Octans au format `$PHLIN,x.xxx,y.yyy,z.zzz*hh`, avec vérification du checksum XOR et gestion des trames série fragmentées.
- Calcul spectral sur une fenêtre glissante de 20 minutes, avec detrend et méthode de Welch.
- Correction du spectre par la RAO du navire et de la direction sélectionnés.
- Affichage de `Hs`, `Tp`, du vent, du courant, des alertes, de l'état de réception et de l'historique.
- Enregistrement horodaté des mesures et des erreurs dans des fichiers SQLite sous `data/`.

## Installation et lancement

Python 3.8 ou ultérieur est recommandé. Tkinter doit être disponible avec l'installation Python.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Le fichier `config.json` fourni démarre en mode UDP. Pour essayer l'interface sans capteurs, régler `inputs.mode` à `simulation`. Le profil de mer utilisé en simulation est défini par `inputs.preset` (`calm`, `moderate`, `rough` ou `instrument`).

## Acquisition

Les transports, hôtes et ports sont définis dans `config.json`. La configuration fournie utilise UDP : Octans sur le port 9998, courant sur 5001 et vent sur 5002. Les hôtes et ports doivent correspondre à l'installation du bord. Le mode série est également disponible pour le flux PHLIN Octans.

Le calcul utilise une fréquence d'échantillonnage configurée actuellement à 5 Hz et limite l'analyse à la bande 0,03-0,5 Hz. Vérifier ces paramètres avec les données et les capteurs réellement utilisés.

## Profils navire et RAO

Le menu **Navire** choisit le profil RAO. Le menu **Direction de houle** choisit l'incidence relative au navire. Le profil configuré actuellement est **IOT - Ile d'Ouessant**, avec une direction initiale de 0°.

Le classeur Excel IOT comporte des onglets nommés par angle. Le lecteur prend la période en secondes de la colonne B et l'amplitude HEAVE de la colonne E, puis convertit la période en fréquence (`f = 1 / T`). Il interpole les gains en fréquence et sélectionne l'onglet d'angle choisi. Hors de la plage de fréquences couverte, le gain est neutre (1), donc aucune correction RAO n'est appliquée.

La correction est appliquée au spectre avant le calcul des deux indicateurs :

```text
PSD_corrigee(f) = PSD_heave(f) / RAO(f)^2
Hs = 4 * sqrt(integrale(PSD_corrigee))
Tp = 1 / frequence_du_pic(PSD_corrigee)
```

Le chemin du classeur IOT dans `config.json` est propre au poste actuel. Pour déplacer le projet, placer le classeur dans le projet et remplacer `rao_file` par un chemin relatif. Pour ajouter un navire, ajouter une entrée dans `vessels` avec `rao_file` et `default_heading_deg`.

## Données et validation

Chaque lancement crée un fichier SQLite horodaté dans `data/`, contenant les mesures et les erreurs relevées. Ces journaux facilitent l'analyse, mais ne constituent pas à eux seuls une validation métrologique.

Avant tout usage opérationnel, valider les conventions de direction, les paramètres d'acquisition, les courbes RAO, le calcul de `Hs` et de `Tp` avec des données réelles et une référence indépendante. Le classeur IOT fourni correspond à la condition « arrival from test to concrete », à vitesse nulle et en profondeur d'eau infinie ; vérifier que ces hypothèses correspondent à la situation d'utilisation.
