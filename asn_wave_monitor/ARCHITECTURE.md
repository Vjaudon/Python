# Architecture technique

## Flux de traitement

`UDP / série / simulation -> décodage -> buffer heave -> spectre Welch -> correction RAO -> Hs et Tp -> interface + fichier texte tabulé`

## Composants

- `UDPReceiver` et `SerialReceiver` acquièrent les données dans des threads dédiés.
- `NMEAParser` et `ExailParser` décodent les messages des capteurs ; `PhlinStreamParser` reconstitue les trames PHLIN reçues par série.
- `Simulator` fournit des signaux de test en mode simulation.
- `WaveProcessor` calcule périodiquement les indicateurs sans bloquer Tkinter.
- `RAOManager` charge les courbes RAO Excel (par angle) ou CSV et fournit le gain interpolé à la fréquence demandée.
- `TextLogger` conserve les mesures et erreurs dans un fichier texte tabulé horodaté.
- `App` gère les sélecteurs de navire et de direction, le tableau de bord, les alertes et l'accès aux journaux enregistrés.

## Calcul de Hs et Tp

1. Les échantillons heave sont conservés dans une fenêtre glissante de 20 minutes.
2. Le signal est détrendé et son spectre de puissance est estimé par Welch.
3. Le spectre est limité à la bande configurée (0,03-0,5 Hz par défaut).
4. Lorsque le profil RAO est chargé, chaque fréquence est corrigée par `PSD_corrigee = PSD_heave / RAO^2`. En dehors de la plage RAO, le gain vaut 1.
5. `m0` est l'intégrale du spectre corrigé et `Hs = 4 * sqrt(m0)`.
6. `Tp` est l'inverse de la fréquence au maximum du spectre corrigé.

## Hypothèses à valider

- compatibilité entre le navire, sa condition de chargement et le classeur RAO sélectionné ;
- direction de houle relative au navire choisie par l'opérateur ;
- fréquence d'échantillonnage, bande analysée et fenêtre de calcul ;
- formats et conventions réels des capteurs UDP/série ;
- seuils d'alerte et précision attendue de Hs et Tp.

Le profil IOT fourni correspond à une condition d'arrivée depuis le test vers le béton, à vitesse nulle et en profondeur d'eau infinie. Une validation sur données réelles et comparaison à une référence restent nécessaires avant tout usage opérationnel.
