const OPENLAYERS_URL = "https://cdn.jsdelivr.net/npm/ol@10.11.0/";
const SWISS_TILES =
    "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/3857/{z}/{x}/{y}.jpeg";

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

export default function renderMap({ parentElement, data, setStateValue }) {
    const canvas = parentElement.querySelector(".runcomfy-map");
    const status = parentElement.querySelector(".map-status");

    // Update the layers on Streamlit reruns so map selections do not reset the zoom.
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

        const source = new ol.source.XYZ({
            url: SWISS_TILES,
            attributions: '© <a href="https://www.swisstopo.admin.ch/" target="_blank" rel="noopener noreferrer">swisstopo</a>',
            maxZoom: 18,
            wrapX: false,
        });

        const project = ({ lng, lat }) => ol.proj.fromLonLat([lng, lat]);
        marker.setGeometry(new ol.geom.Point(project(currentData.center)));
        markers.addFeature(marker);

        source.on("tileloadend", () => {
            if (!disposed && !tileLoaded) status.textContent = "";
            tileLoaded = true;
        });
        source.on("tileloaderror", () => {
            if (!disposed && !tileLoaded) {
                status.textContent = "Swiss map tiles could not load.";
            }
        });

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

        draw = () => {
            const {
                center,
                pending,
                revision,
                routes: options,
                routeView,
            } = currentData;

            setPreview(pending);

            const viewKey = JSON.stringify([
                revision,
                center,
                options,
                routeView,
            ]);
            if (viewKey === lastViewKey) return;
            lastViewKey = viewKey;

            // Outline each route and fit the map to the visible paths and the start.
            const start = project(center);
            marker.setGeometry(new ol.geom.Point(start));
            routes.clear();

            const visible = routeView ? [options[routeView - 1]] : options;
            let invalidRoute = false;

            for (const [index, route] of visible.entries()) {
                const points = route?.path;

                if (
                    !Array.isArray(points) ||
                    points.length < 2 ||
                    !points.every(
                        (point) =>
                            Array.isArray(point) &&
                            point.length >= 2 &&
                            Number.isFinite(point[0]) &&
                            Number.isFinite(point[1]) &&
                            point[0] >= -180 &&
                            point[0] <= 180 &&
                            point[1] >= -90 &&
                            point[1] <= 90,
                    )
                ) {
                    console.error("Invalid route coordinates; route was not drawn:", {
                        label: route?.label,
                        pointCount: Array.isArray(points) ? points.length : null,
                        firstPoint: points?.[0],
                    });
                    invalidRoute = true;
                    continue;
                }

                const path = new ol.geom.LineString(
                    points.map(([lng, lat]) => ol.proj.fromLonLat([lng, lat])),
                );
                const feature = new ol.Feature();
                feature.setGeometry(path);
                feature.set("label", route.label);

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

            if (invalidRoute) {
                status.textContent =
                    "A generated route has invalid coordinates and could not be drawn.";
            } else if (tileLoaded) {
                status.textContent = routeView ? visible[0].label : "";
            }
        };

        draw();

        map.on("singleclick", (event) => {
            // Show a clicked route's label or send a candidate starting point to Python.
            if (!currentData.pickOnRoute) {
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
            }

            const [lng, lat] = ol.proj.toLonLat(event.coordinate);
            setPreview({ lng, lat });
            if (tileLoaded) status.textContent = "";
            send("point", { lat, lng, revision: currentData.revision });
        });
    }).catch(() => {
        if (!disposed) {
            status.textContent = "The swisstopo map could not be initialized.";
        }
    });

    function update(nextData, nextSender) {
        currentData = nextData;
        send = nextSender;
        draw?.();
    }

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