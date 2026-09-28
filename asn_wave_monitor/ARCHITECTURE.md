# Architecture technique

## Modules

- `UDPReceiver` : transport réseau non bloquant, en thread.
- `NMEAParser` : couche d'adaptation des trames capteurs.
- `Simulator` : générateur de données pour démonstration et tests.
- `compute_wave()` : traitement spectral.
- `CSVLogger` : traçabilité des données.
- `App` : interface opérateur.

## Traitement Hs/Tp

1. Les échantillons heave sont conservés dans une fenêtre de 20 minutes.
2. Le signal est détrendé.
3. Le spectre de puissance est estimé par méthode de Welch.
4. Si une RAO est disponible, le spectre peut être corrigé.
5. `m0` est l'intégrale du spectre.
6. `Hs = 4 * sqrt(m0)`.
7. `Tp = 1 / fp`, avec `fp` fréquence du maximum spectral.

## Points à valider

- fréquence d'échantillonnage réelle Octans ;
- format BACUSTOM2/stdbin ;
- définition et format de la RAO ;
- conventions de direction ;
- fréquence des mesures courant/vent ;
- seuils opérationnels ;
- précision attendue de Hs.
