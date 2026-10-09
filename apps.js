import { counties, kenyaLocations } from "./kenyalocations.js";

const form = document.querySelector("#registration-form");
const county = document.querySelector("#county");
const constituency = document.querySelector("#constituency");
const forms = [...document.querySelectorAll("[data-form-step]")];
const sidebar = [...document.querySelectorAll("[data-side-step]")];
const bars = [...document.querySelectorAll(".progress-bar")];
const back = document.querySelector("#back-button");
const signIn = document.querySelector("#sign-in");
const password = document.querySelector("#password");
const confirmation = document.querySelector("#confirm-password");
const passwordError = document.querySelector("#password-error");
let step = 0;

const content = [
  ["Personal details", "Let’s start with the student’s official details."],
  ["Location & education", "Help us connect you to the correct NG-CDF office."],
  ["Secure account", "Create secure sign-in details for your bursary account."],
];

counties.forEach((name) => county.add(new Option(name, name)));
county.addEventListener("change", () => {
  constituency.innerHTML = "";
  constituency.add(new Option(county.value ? "Select your constituency" : "Choose a county first", ""));
  constituency.disabled = !county.value;
  (kenyaLocations[county.value] || []).forEach((name) => constituency.add(new Option(name, name)));
});

function showStep(next) {
  step = next;
  forms.forEach((item, index) => item.classList.toggle("hidden", index !== step));
  sidebar.forEach((item, index) => {
    item.classList.toggle("active", index === step);
    item.classList.toggle("complete", index < step);
    item.querySelector(".step-number").textContent = index < step ? "✓" : String(index + 1);
  });
  bars.forEach((item, index) => item.classList.toggle("active", index <= step));
  document.querySelector("#step-count").textContent = `Step ${step + 1} of 3`;
  document.querySelector("#step-title").textContent = content[step][0];
  document.querySelector("#step-copy").textContent = content[step][1];
  back.classList.toggle("hidden", step === 0);
  signIn.classList.toggle("hidden", step !== 0);
  document.querySelector("#continue-label").textContent = step === 2 ? "Create account" : "Continue";
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const fields = [...forms[step].querySelectorAll("input, select")];
  const firstInvalidField = fields.find((field) => !field.checkValidity());
  const formError = document.querySelector("#form-error");
  if (firstInvalidField) {
    formError.classList.remove("hidden");
    firstInvalidField.reportValidity();
    firstInvalidField.focus();
    return;
  }
  formError.classList.add("hidden");
  if (step < 2) return showStep(step + 1);
  if ((password.value || confirmation.value) && password.value !== confirmation.value) {
    passwordError.classList.remove("hidden");
    confirmation.focus();
    return;
  }
  window.location.href = "./loading.html";
});

back.addEventListener("click", () => showStep(step - 1));
form.addEventListener("input", () => document.querySelector("#form-error").classList.add("hidden"));
document.querySelector("#toggle-password").addEventListener("click", (event) => {
  const showing = password.type === "text";
  password.type = showing ? "password" : "text";
  event.currentTarget.textContent = showing ? "Show" : "Hide";
});
confirmation.addEventListener("input", () => passwordError.classList.add("hidden"));
window.addEventListener("offline", () => { window.location.href = "./offline.html"; });
