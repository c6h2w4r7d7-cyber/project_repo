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
    // Streamlit can invoke the renderer again on the same element after a rerun.
    canvas.runComfyMapCleanup?.();
    status.textContent = "Loading swisstopo map…";
    let disposed = false;
    let map;
    let tileLoaded = false;

    loadOpenLayers().then((ol) => {
        if (disposed) return;
        const center = ol.proj.fromLonLat([data.center.lng, data.center.lat]);
        const marker = new ol.Feature(new ol.geom.Point(center));
        marker.setStyle(new ol.style.Style({
            image: new ol.style.Circle({
                radius: 8,
                fill: new ol.style.Fill({ color: "#932534" }),
                stroke: new ol.style.Stroke({ color: "#fff", width: 3 }),
            }),
            zIndex: 10,
        }));

        const features = [marker];
        for (const [index, route] of (data.routes || []).entries()) {
            const path = new ol.geom.LineString(route.path.map((point) => ol.proj.fromLonLat(point)));
            const feature = new ol.Feature({ geometry: path, label: route.label });
            const zIndex = (data.routes.length - index) * 2;
            feature.setStyle([
                new ol.style.Style({
                    stroke: new ol.style.Stroke({ color: "#fff", width: 8 }),
                    zIndex,
                }),
                new ol.style.Style({
                    stroke: new ol.style.Stroke({ color: route.color, width: 5 }),
                    zIndex: zIndex + 1,
                }),
            ]);
            features.push(feature);
        }

        const source = new ol.source.XYZ({
            url: SWISS_TILES,
            attributions: '© <a href="https://www.swisstopo.admin.ch/" target="_blank" rel="noopener noreferrer">swisstopo</a>',
            maxZoom: 18,
            wrapX: false,
        });
        source.on("tileloadend", () => {
            tileLoaded = true;
            if (!disposed) status.textContent = "";
        });
        source.on("tileloaderror", () => {
            if (!disposed && !tileLoaded) status.textContent = "Swiss map tiles could not load.";
        });
        const overlay = new ol.source.Vector({ features });
        const viewOptions = { center, zoom: 14, minZoom: 7, maxZoom: 19 };
        if (data.selectable) {
            viewOptions.extent = ol.proj.transformExtent([5.8, 45.7, 10.7, 47.9], "EPSG:4326", "EPSG:3857");
        }
        map = new ol.Map({
            target: canvas,
            layers: [new ol.layer.Tile({ source }), new ol.layer.Vector({ source: overlay })],
            view: new ol.View(viewOptions),
            controls: ol.control.defaults.defaults({ attributionOptions: { collapsible: false } }),
        });

        if (data.selectable) {
            map.on("singleclick", ({ coordinate }) => {
                const [lng, lat] = ol.proj.toLonLat(coordinate);
                setStateValue("point", { lat, lng, revision: data.revision });
            });
        } else if (features.length > 1) {
            map.getView().fit(overlay.getExtent(), { padding: [32, 32, 32, 32], maxZoom: 16 });
            map.on("singleclick", (event) => {
                const label = map.forEachFeatureAtPixel(event.pixel, (feature) => feature.get("label"), {
                    hitTolerance: 4,
                });
                status.textContent = label || "";
            });
        }
    }).catch(() => {
        if (!disposed) status.textContent = "The swisstopo map could not be initialized.";
    });

    function cleanup() {
        if (disposed) return;
        disposed = true;
        if (map) {
            map.setTarget(undefined);
            map.dispose();
        }
        if (canvas.runComfyMapCleanup === cleanup) {
            canvas.replaceChildren();
            delete canvas.runComfyMapCleanup;
        }
    }
    canvas.runComfyMapCleanup = cleanup;
    return cleanup;
}
