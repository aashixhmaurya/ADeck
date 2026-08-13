(() => {
    "use strict";
    const APP_VERSION = "0.3.0-alpha";
    const SLOTS_PER_PROFILE = 6;
    const STORAGE_KEY = "adeck_data";
    let state = {
        profiles: [
            { id: "p1", name: "dev tools" }
        ],
        activeProfileId: "p1",
        activeSlotIndex: null
    };
    const els = {
        profileList: document.getElementById("profileList"),
        addProfileBtn: document.getElementById("addProfileBtn"),
        slotGrid: document.getElementById("slotGrid"),
        navBtns: document.querySelectorAll(".nav-btn"),
        editorPanel: document.getElementById("editorPanel")
    };

    function loadState() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            try {
                state = JSON.parse(saved);
            } catch (e) {
                console.error("state parse fail");
            }
        }
    }

    function saveState() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    }

    function renderProfiles() {
        els.profileList.innerHTML = "";
        state.profiles.forEach(p => {
            const li = document.createElement("li");
            li.className = p.id === state.activeProfileId ? "profile-item active" : "profile-item";
            li.textContent = p.name;
            li.addEventListener("click", () => {
                state.activeProfileId = p.id;
                state.activeSlotIndex = null;
                saveState();
                renderAll();
            });
            els.profileList.appendChild(li);
        });
    }

    function renderGrid() {
        els.slotGrid.innerHTML = "";
        for (let i = 0; i < SLOTS_PER_PROFILE; i++) {
            const slot = document.createElement("div");
            slot.className = i === state.activeSlotIndex ? "slot active" : "slot";
            slot.innerHTML = `<span class="slot-num">0${i + 1}</span>`;
            slot.addEventListener("click", () => {
                state.activeSlotIndex = i;
                saveState();
                renderGrid();
                renderEditor();
            });
            els.slotGrid.appendChild(slot);
        }
    }

    function renderEditor() {
        if (state.activeSlotIndex === null) {
            els.editorPanel.innerHTML = `<span class="mono muted">SELECT A SLOT TO EDIT</span>`;
        } else {
            els.editorPanel.innerHTML = `<div class="mono">EDITING SLOT 0${state.activeSlotIndex + 1}<br><br></div>`;
        }
    }

    function renderAll() {
        renderProfiles();
        renderGrid();
        renderEditor();
    }

    function wireEvents() {
        els.navBtns.forEach((btn) => {
            btn.addEventListener("click", (e) => {
                document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
                e.target.classList.add("active");
            });
        });
        els.addProfileBtn.addEventListener("click", () => {
            const newId = "p" + Date.now();
            state.profiles.push({ id: newId, name: "new profile" });
            state.activeProfileId = newId;
            state.activeSlotIndex = null;
            saveState();
            renderAll();
        });
    }

    function boot() {
        loadState();
        wireEvents();
        renderAll();
    }
    boot();
})();