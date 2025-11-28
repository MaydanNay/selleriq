const connectCard = document.getElementById('business');
const sellCard = document.getElementById('manager');
const roleInput = document.getElementById('role-input');
const continueButton = document.getElementById('continue-button');
const roleForm = document.getElementById('role-form');
const errorMessage = document.getElementById('error-message');

connectCard.addEventListener('click', () => {
    connectCard.classList.add('selected');
    sellCard.classList.remove('selected');
    roleInput.value = 'business';
    continueButton.disabled = false;
    errorMessage.style.display = 'none';
});

sellCard.addEventListener('click', () => {
    sellCard.classList.add('selected');
    connectCard.classList.remove('selected');
    roleInput.value = 'manager';
    continueButton.disabled = false;
    errorMessage.style.display = 'none';
});

roleForm.addEventListener('submit', (e) => {
    if (!roleInput.value) {
    e.preventDefault();
    errorMessage.style.display = 'block';
    }
});