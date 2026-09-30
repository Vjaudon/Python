# ASN Wave Monitor

Prototype fonctionnel basé sur le cahier des charges ASN « Projet affichage Hs Tp ».

## Ce qui est déjà implémenté

- acquisition locale en mode simulation ;
- architecture d'acquisition UDP séparée des traitements ;
- stockage CSV des données brutes et des résultats ;
- fenêtre glissante de 20 minutes pour le heave ;
- analyse spectrale Welch/FFT ;
- calcul `Hs = 4 * sqrt(m0)` ;
- calcul de `Tp` par fréquence du pic spectral ;
- affichage temps réel Hs, Tp, courant et vent ;
- seuils configurables pour Hs, vent et courant ;
- préparation d'un mode UDP pour les trois capteurs ;
- décodage `$PHLIN,x.xxx,y.yyy,z.zzz*hh` de l'heave Octans sur flux série ;
- code structuré pour ajouter les décodeurs réels Octans/Exail, Valeport et anémomètre.

## Installation

Python 3.8+ est recommandé.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Au premier lancement, l'application est en **simulation**. Les fichiers sont écrits dans `data/`.

## Passage à l'acquisition réelle

Modifier `config.json` :

```json
"inputs": {
  "mode": "udp",
  "octans": {"transport": "udp", "host": "0.0.0.0", "port": 5000},
  "current": {"transport": "udp", "host": "0.0.0.0", "port": 5001},
  "wind": {"transport": "udp", "host": "0.0.0.0", "port": 5002}
}
```

Les ports sont des exemples et doivent être remplacés par ceux du bord.

### Octans PHLIN

Le flux série Octans est décodé au format `$PHLIN,x.xxx,y.yyy,z.zzz*hh<CR><LF>`. Le troisième champ numérique `z.zzz` est utilisé comme heave en mètres. Le parseur vérifie le checksum XOR `hh` et gère les lectures fragmentées ou contenant plusieurs trames.

## RAO

Le menu **Navire** sélectionne le profil RAO utilisé pour corriger le spectre. Le menu **Direction de houle** sélectionne l'angle relatif au navire ; les classeurs Excel utilisent les onglets numériques d'angle, la période en colonne B et l'amplitude HEAVE en colonne E. Les fréquences sont calculées comme l'inverse des périodes. Hors de la plage couverte par la courbe, aucune correction RAO n'est appliquée.

Le profil IOT fourni est déclaré dans `config.json`. Son chemin Excel est propre à ce poste ; pour déplacer le projet, copier le classeur dans le projet et remplacer `rao_file` par son chemin relatif. Pour ajouter un bateau, ajouter une entrée dans `vessels` avec `rao_file` et `default_heading_deg`.

## Validation

Le prototype ne doit pas être utilisé comme instrument opérationnel avant validation avec des données Octans réelles et comparaison avec une référence. Le cahier des charges précise que la précision de Hs reste à définir et à valider avec les données réelles.

## Architecture cible

`Acquisition -> Décodage -> Buffer heave 20 min -> Spectre -> RAO optionnelle -> Hs/Tp -> Alertes -> Affichage + Enregistrement`

## Évolutions recommandées

1. Implémenter les trames officielles Exail BACUSTOM2/stdbin.
2. Ajouter pyserial pour les ports série réels.
3. Ajouter un import de fichiers de test et un lecteur « replay ».
4. Ajouter une vue spectrale et les statistiques qualité des données.
5. Ajouter une configuration GUI des seuils et interfaces.
6. Ajouter SQLite en option et une signature/intégrité des fichiers pour la traçabilité.
7. Ajouter tests automatiques avec jeux de données de référence.
8. Générer un exécutable Windows après validation (`PyInstaller`).
