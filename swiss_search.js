export default function renderSwissSearch({ parentElement, data, setTriggerValue }) {
    const form = parentElement.querySelector(".swiss-location-search");
    const input = form.querySelector("input");
    const list = form.querySelector("[role=listbox]");
    const status = form.querySelector("[role=status]");

    if (form.runComfySearch) {
        form.runComfySearch.update(data, setTriggerValue);
        return form.runComfySearch.cleanup;
    }

    input.value = data.lastQuery;
    const listeners = new AbortController();
    const events = { signal: listeners.signal };
    let timer;
    let pending;
    let nextId = 0;
    let matches = [];
    let active = -1;
    let send = setTriggerValue;

    function cancelLookup() {
        clearTimeout(timer);
        pending = undefined;
    }

    function highlight(index) {
        active = index;
        for (const [i, option] of [...list.children].entries()) {
            option.setAttribute("aria-selected", String(i === active));
        }
        const option = list.children[active];
        if (option) {
            input.setAttribute("aria-activedescendant", option.id);
            option.scrollIntoView({ block: "nearest" });
        } else {
            input.removeAttribute("aria-activedescendant");
        }
    }

    function closeList() {
        list.hidden = true;
        input.setAttribute("aria-expanded", "false");
        highlight(-1);
    }

    function openList() {
        if (!matches.length) return;
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
    }

    function submit(selection) {
        const query = input.value.trim();
        if (!query) {
            status.textContent = "Enter a Swiss address or location.";
            return;
        }

        cancelLookup();
        closeList();
        matches = [];
        list.replaceChildren();
        status.textContent = "";
        if (selection) input.value = selection.label;

        send("submit", { query, selectionId: selection?.id ?? null });
    }

    function queueLookup() {
        cancelLookup();
        closeList();
        matches = [];
        list.replaceChildren();
        status.textContent = "";

        const query = input.value.trim();
        if (query.length < 2) return;

        timer = setTimeout(() => {
            pending = { query, id: ++nextId };
            status.textContent = "Looking for Swiss locations…";
            send("lookup", pending);
        }, 300);
    }

    function update(nextData, nextSender) {
        send = nextSender;
        const result = nextData.suggestions;
        if (!pending || !result || result.id !== pending.id || result.query !== pending.query) return;
        if (input.value.trim() !== pending.query) return;
        pending = undefined;

        matches = result.matches;
        for (const [index, match] of matches.entries()) {
            const option = document.createElement("li");
            option.id = `swiss-search-option-${index}`;
            option.setAttribute("role", "option");
            option.setAttribute("aria-selected", "false");
            option.textContent = match.label;
            option.addEventListener("pointerdown", (event) => event.preventDefault(), events);
            option.addEventListener("click", () => submit(match), events);
            list.append(option);
        }

        if (input.matches(":focus")) openList();
        status.textContent = result.error
            ? "Suggestions unavailable. You can still search."
            : matches.length
                ? `${matches.length} suggestions available.`
                : "No matching Swiss locations.";
    }

    closeList();
    list.replaceChildren();
    status.textContent = "";

    input.addEventListener("input", queueLookup, events);
    input.addEventListener("focus", openList, events);

    form.addEventListener("focusout", (event) => {
        if (!form.contains(event.relatedTarget)) closeList();
    }, events);

    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !list.hidden) {
            event.preventDefault();
            closeList();
        } else if (!event.isComposing && matches.length && ["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            openList();
            const offset = event.key === "ArrowDown" ? 1 : -1;
            const start = active < 0 && offset < 0 ? 0 : active;
            highlight((start + offset + matches.length) % matches.length);
        }
    }, events);

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        submit(list.hidden ? undefined : matches[active >= 0 ? active : 0]);
    }, events);

    function cleanup() {
        listeners.abort();
        cancelLookup();
        if (form.runComfySearch?.cleanup === cleanup) delete form.runComfySearch;
    }

    form.runComfySearch = { update, cleanup };
    return cleanup;
}