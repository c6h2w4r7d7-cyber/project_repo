# Running RunComfy with swisstopo

Install the dependencies and start the app from the project directory.

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

No API keys are required for local use. Search for a Swiss location or click the swisstopo map and confirm the start. Choose a distance and generate routes. The results show up to three pedestrian loops on the Swiss national map, with distance, elevation gain, estimated forest coverage, and the RunComfy score.

- Map tiles, place search, elevation profiles, and the swissTLM3D forest layer come from the Swiss federal geoportal. Elevation gain is calculated from a sampled terrain profile. Forest coverage uses points spaced along the route. [GeoAdmin API documentation](https://docs.geo.admin.ch/) · [Elevation profiles](https://docs.geo.admin.ch/access-data/get-elevation-profile.html) · [Forest layer](https://api3.geo.admin.ch/rest/services/api/MapServer/ch.swisstopo.swisstlm3d-wald/legend)
- The public federal geoportal has no documented walking route endpoint. RunComfy uses Valhalla's pedestrian profile with OpenStreetMap data to calculate loops. For development and light personal use, the default is the shared FOSSGIS demo service. For a public or higher-traffic deployment, set `RUNCOMFY_ROUTER_URL` in Streamlit Secrets or the environment to the full `/route` URL of your Valhalla instance. [Valhalla demo and deployment guidance](https://valhalla.github.io/valhalla/start/introduction/)
- Weather and air quality use Open-Meteo.

WHEN the user types at least two characters:
    Wait 300 milliseconds after the last keystroke.
    Ask GeoAdmin for up to five matching Swiss locations.
    Show the suggestions only if they match the current input.

WHEN the user presses an arrow key:
    Highlight the next or previous suggestion.

WHEN the user clicks a suggestion, presses Enter, or clicks Search location:
    Use the chosen suggestion, or the first match for the typed text.
    If a match is found, move the start marker and clear the previous routes.
    Otherwise, keep the current starting point and show a message.