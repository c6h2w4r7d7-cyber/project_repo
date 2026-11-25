// AI use: generated with ChatGPT (OpenAI, 2026); simplified and commented
// with Claude (Anthropic, Claude Opus 5.5, 2026). See README.md, "AI use".
//
// The swisstopo map, drawn with the OpenLayers library (https://openlayers.org).
// Python sends: start point, routes, which route to show.
// The map sends back: the point the user clicked (as a new start candidate).
// Clicking a route shows its name instead.

const OPENLAYERS_URL = "https://cdn.jsdelivr.net/npm/ol@10.11.0/";
const SWISS_TILES =
    "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/3857/{z}/{x}/{y}.jpeg";

// Load the OpenLayers library once from the internet. "integrity" makes the
// browser check that the downloaded file is exactly the expected one.
function loadOpenLayers() {
    if (window.runComfyOpenLayers) return window.runComfyOpenLayers;

    window.runComfyOpenLayers = new Promise((resolve, reject) => {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = OPENLAYERS_URL + "ol.css";
        css.integrity = "sha384-Jpg1uvTciFJuHq+90Ly0/2SKRT9yS5OhbIN5FuFoFWji9fc44ok8xxO88CJi8Z5W";
        css.crossOrigin = "anonymous";
        document.head.append(css);

        const script = document.createElement("script");
        script.src = OPENLAYERS_URL + "dist/ol.js";
        script.integrity = "sha384-rwbCGPbgxLkcQaFvIra1Vz3KBT1yBeF2/1VgLs/gCCNCJ61GHJGimHpkufVKcqap";
        script.crossOrigin = "anonymous";
        script.onload = () => resolve(window.ol);
        script.onerror = reject;
        document.head.append(script);
    });

    return window.runComfyOpenLayers;
}

// Streamlit calls this function on every rerun. The first call builds the map;
// later calls only update it, so the zoom and position stay where they are.
export default function renderMap({ parentElement, data, setStateValue }) {
    const canvas = parentElement.querySelector(".runcomfy-map");
    const status = parentElement.querySelector(".map-status");  // short messages under the map

    if (canvas.runComfyMap) {
        canvas.runComfyMap.update(data, setStateValue);
        return canvas.runComfyMap.cleanup;
    }

    const instance = { update, cleanup };
    canvas.runComfyMap = instance;
    status.textContent = "Loading swisstopo map…";

    let disposed = false;
    let map;
    let tileLoaded = false;
    let currentData = data;
    let send = setStateValue;
    let draw;

    loadOpenLayers().then((ol) => {
        if (disposed) return;

        // Containers for what we draw: the routes, the start marker (red) and
        // the preview of a clicked point (blue).
        const routes = new ol.source.Vector();
        const markers = new ol.source.Vector();
        const marker = new ol.Feature();
        const preview = new ol.Feature();

        // Keep the start marker above every route with a dark rim and white ring.
        marker.setStyle([
            pointStyle(15, "#172334", "#172334", 2),
            pointStyle(11, "#c81c43", "#fff", 4),
        ]);
        preview.setStyle(pointStyle(8, "#1554c4", "#fff", 3));

        function pointStyle(radius, fill, stroke, width) {
            return new ol.style.Style({
                image: new ol.style.Circle({
                    radius,
                    fill: new ol.style.Fill({ color: fill }),
                    stroke: new ol.style.Stroke({ color: stroke, width }),
                }),
            });
        }

        // The swisstopo map, loaded as small image tiles.
        const source = new ol.source.XYZ({
            url: SWISS_TILES,
            attributions: '© <a href="https://www.swisstopo.admin.ch/" target="_blank" rel="noopener noreferrer">swisstopo</a>',
            maxZoom: 18,
            wrapX: false,
        });

        const project = ({ lng, lat }) => ol.proj.fromLonLat([lng, lat]);
        marker.setGeometry(new ol.geom.Point(project(currentData.center)));
        markers.addFeature(marker);

        // Remove "Loading…" when the first tile arrives, or say that tiles failed.
        source.on("tileloadend", () => {
            if (!disposed && !tileLoaded) status.textContent = "";
            tileLoaded = true;
        });
        source.on("tileloaderror", () => {
            if (!disposed && !tileLoaded) {
                status.textContent = "Swiss map tiles could not load.";
            }
        });

        // The map: three layers from bottom to top (map tiles, routes, markers),
        // starting at zoom 14 around the start. It cannot be moved away from Switzerland.
        const routeLayer = new ol.layer.Vector({ source: routes });
        map = new ol.Map({
            target: canvas,
            layers: [
                new ol.layer.Tile({ source }),
                routeLayer,
                new ol.layer.Vector({ source: markers }),
            ],
            view: new ol.View({
                center: project(currentData.center),
                zoom: 14,
                minZoom: 7,
                maxZoom: 19,
                extent: ol.proj.transformExtent(
                    [5.8, 45.7, 10.7, 47.9],
                    "EPSG:4326",
                    "EPSG:3857",
                ),
            }),
            controls: ol.control.defaults.defaults({
                attributionOptions: { collapsible: false },
            }),
        });

        let lastViewKey;
        let previewVisible = false;

        // Show the blue dot at the clicked point, or hide it (point = null).
        function setPreview(point) {
            if (point) {
                preview.setGeometry(new ol.geom.Point(project(point)));
                if (!previewVisible) {
                    markers.addFeature(preview);
                    previewVisible = true;
                }
            } else if (previewVisible) {
                markers.removeFeature(preview);
                previewVisible = false;
            }
        }

        // Draw the data from Python: start marker, routes and the clicked point.
        draw = () => {
            const {
                center,
                pending,
                revision,
                routes: options,
                routeView,
            } = currentData;

            setPreview(pending);

            // Redraw the routes only if they changed; otherwise the map would
            // jump back to the routes after every click.
            const viewKey = JSON.stringify([
                revision,
                center,
                options,
                routeView,
            ]);
            if (viewKey === lastViewKey) return;
            lastViewKey = viewKey;

            const start = project(center);
            marker.setGeometry(new ol.geom.Point(start));
            routes.clear();

            // routeView 0 = all routes, 1–3 = only that route.
            const visible = routeView ? [options[routeView - 1]] : options;

            for (const [index, route] of visible.entries()) {
                const path = new ol.geom.LineString(
                    route.path.map(([lng, lat]) => ol.proj.fromLonLat([lng, lat])),
                );
                const feature = new ol.Feature();
                feature.setGeometry(path);
                feature.set("label", route.label);

                // Each route: a white outline under a coloured line; route 1 on top.
                const zIndex = (visible.length - index) * 2;
                feature.setStyle([
                    new ol.style.Style({
                        stroke: new ol.style.Stroke({ color: "#fff", width: 12 }),
                        zIndex,
                    }),
                    new ol.style.Style({
                        stroke: new ol.style.Stroke({
                            color: route.color,
                            width: 7,
                        }),
                        zIndex: zIndex + 1,
                    }),
                ]);
                routes.addFeature(feature);
            }

            // Zoom so that the visible routes and the start fit on the map.
            const view = map.getView();
            if (routes.getFeatures().length) {
                const extent = routes.getExtent();
                ol.extent.extendCoordinate(extent, start);
                view.fit(extent, {
                    padding: [36, 36, 36, 36],
                    maxZoom: 16,
                });
            } else {
                view.setCenter(start);
                view.setZoom(14);
            }

            if (tileLoaded) status.textContent = routeView ? visible[0].label : "";
        };

        draw();

        map.on("singleclick", (event) => {
            // Show a clicked route's label or send a candidate starting point to Python.
            const label = map.forEachFeatureAtPixel(
                event.pixel,
                (feature) => feature.get("label"),
                {
                    hitTolerance: 4,
                    layerFilter: (layer) => layer === routeLayer,
                },
            );
            if (label) {
                status.textContent = label;
                return;
            }

            const [lng, lat] = ol.proj.toLonLat(event.coordinate);
            setPreview({ lng, lat });
            if (tileLoaded) status.textContent = "";
            // Send the point to Python (picker.point in app.py), which reruns the page.
            send("point", { lat, lng, revision: currentData.revision });
        });
    }).catch(() => {
        if (!disposed) {
            status.textContent = "The swisstopo map could not be initialized.";
        }
    });

    // Called on every later rerun: take the new data from Python and redraw.
    function update(nextData, nextSender) {
        currentData = nextData;
        send = nextSender;
        draw?.();
    }

    // Called by Streamlit when the map is removed from the page.
    function cleanup() {
        if (disposed) return;
        disposed = true;

        if (map) {
            map.setTarget(undefined);
            map.dispose();
        }

        if (canvas.runComfyMap === instance) {
            canvas.replaceChildren();
            delete canvas.runComfyMap;
        }
    }

    return cleanup;
}