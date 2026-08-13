(() => {
    "use strict";
    console.log("ADECK Dev Build Initialized...");
    console.log("TODO: Build Profile rendering logic");
    console.log("TODO: Implement hardware grid preview");
    const APP_VERSION = "0.1.0-alpha";
    const SLOTS_PER_PROFILE = 6;
    const state = {
        profiles: [],
        activeProfileId: null,
        activeSlotIndex: null,
        dirty: false
    };
    const els = {
        profileList: document.getElementById("profileList"),
        navBtns: document.querySelectorAll(".nav-btn")
    };
    function renderProfiles() {
        console.warn("renderProfiles() not implemented yet.");
    }
    function wireEvents() {
        els.navBtns.forEach((btn) => {
            btn.addEventListener("click", (e) => {
                console.log("Navigation clicked, but routing is disabled in this build.");
            });
        });
    }
    function boot() {
        console.log(`Booting ADeck v${APP_VERSION}`);
        wireEvents();
    }
    boot();
})();
