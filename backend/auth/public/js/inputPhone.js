function initPhoneInput() {
    const phoneInput = document.querySelector("#phone");
    if (!phoneInput) return;

    const form = document.getElementById("loginForm") || document.getElementById("registerForm");
    const iti = window.intlTelInput(phoneInput, {
        initialCountry: "kz",
        onlyCountries: ["kz", "ru", "uz", "kg", "by", "ua"],
        
        // Отключаем «национальный» формат
        nationalMode: false,
        autoHideDialCode: false,
        separateDialCode: false,
        customPlaceholder: (placeholder, country) => "+" + country.dialCode,
        geoIpLookup: cb => cb("kz"),
        // customPlaceholder: function(selectedCountryPlaceholder, selectedCountryData) {
            // return '+' + selectedCountryData.dialCode;
        // },
        // geoIpLookup: function(callback) {
            // callback("kz");
        // },
        utilsScript: "https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.8/js/utils.js"
    });

    function setFixedPrefix() {
        const prefix = '+' + iti.getSelectedCountryData().dialCode;
        if (!phoneInput.value.startsWith(prefix)) {
            phoneInput.value = prefix;
        }
        // Всегда ставим курсор сразу после префикса
        const pos = prefix.length;
        phoneInput.setSelectionRange(pos, pos);
    }

    // Делаем +7 всегда в поле и не даём его стереть
    phoneInput.addEventListener("focus", setFixedPrefix);
    phoneInput.addEventListener("countrychange", setFixedPrefix);


    // Фильтруем ввод “не‑цифр” и обрезаем длину после префикса
    phoneInput.addEventListener("input", () => {
        const prefix = "+" + iti.getSelectedCountryData().dialCode;
        let rest = phoneInput.value.replace(/\D/g, "").slice(prefix.replace(/\D/g, "").length);
        phoneInput.value = prefix + rest;
    });

    // Блокируем Backspace/Delete внутри префикса
    phoneInput.addEventListener("keydown", e => {
        const prefix = '+' + iti.getSelectedCountryData().dialCode;
        const caretPos = phoneInput.selectionStart;
        if ((e.key === "Backspace" || e.key === "Delete") && caretPos <= prefix.length) {
            e.preventDefault();
        }

        // Лимит цифр после префикса
        if (/\d/.test(e.key)) {
            const afterPrefix = phoneInput.value.slice(prefix.length).replace(/\D/g, '');
            if (afterPrefix.length >= 10) {
                e.preventDefault();
            }
        }
    });

    // Блокируем выделение части префикса
    phoneInput.addEventListener("selectstart", e => {
        const prefix = "+" + iti.getSelectedCountryData().dialCode;
        if (phoneInput.selectionStart < prefix.length) {
            e.preventDefault();
            setFixedPrefix();
        }
    });

    // На submit отдаём полный номер
    form?.addEventListener("submit", () => {
        phoneInput.value = iti.getNumber();
    });
}