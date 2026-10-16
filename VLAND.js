const authForm = document.getElementById('authForm');
const formTitle = document.getElementById('formTitle');
const submitBtn = document.getElementById('submitBtn');
const toggleText = document.getElementById('toggleText');
const messageEl = document.getElementById('message');

let isLoginMode = true;

// Auto-detects the server: works locally (127.0.0.1:5000) and on Render
const BACKEND_URL = window.location.origin;

toggleText.addEventListener('click', () => {
    isLoginMode = !isLoginMode;
    messageEl.className = "message";
    messageEl.innerText = "";
    if (isLoginMode) {
        formTitle.innerText = "FodaKem VIP";
        submitBtn.innerText = "Sign In";
        toggleText.innerText = "Need a premium account? Register here";
    } else {
        formTitle.innerText = "Create FodaKem VIP Account";
        submitBtn.innerText = "Register VIP Profile";
        toggleText.innerText = "Already have an account? Sign In";
    }
});

authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const usernameInput = document.getElementById('username').value;
    const passwordInput = document.getElementById('password').value;
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner"></span> Processing...`;
    messageEl.className = "message";

    const targetUrl = isLoginMode ? `${BACKEND_URL}/api/login` : `${BACKEND_URL}/api/register`;

    try {
        const response = await fetch(targetUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: usernameInput, password: passwordInput })
        });

        const data = await response.json();

        if (response.ok) {
            localStorage.setItem('active_user', usernameInput);
            messageEl.className = "message success";
            messageEl.innerText = data.message;
            setTimeout(() => {
                window.location.href = isLoginMode ? 'dashboard.html' : 'VIP-CARD.html';
            }, 1000);
        } else {
            messageEl.className = "message error";
            messageEl.innerText = data.message;
            submitBtn.disabled = false;
            submitBtn.innerText = isLoginMode ? "Sign In to Portal" : "Register VIP Profile";
        }
    } catch (error) {
        messageEl.className = "message error";
        messageEl.innerText = "Error: Cannot establish network pipeline connection to FodaKem VIP cloud server.";
        submitBtn.disabled = false;
        submitBtn.innerText = isLoginMode ? "Sign In to Portal" : "Register VIP Profile";
    }
});
