function togglePasswordVisibility(fieldId, iconId) {
    const passwordInput = document.getElementById(fieldId);
    const passwordIcon = document.getElementById(iconId);
    if (!passwordInput || !passwordIcon) return;

    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        passwordIcon.src = '/common/images/off.ico';
    } else {
        passwordInput.type = 'password';
        passwordIcon.src = '/common/images/on.ico';
    }
}
