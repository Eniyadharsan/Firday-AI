# JARVIS Mobile App

Personal AI Assistant — works on iPhone, Android, and Web.

## Quick Setup

### 1. Install dependencies
```bash
cd jarvis-mobile
npm install
```

### 2. Configure server URL
Open `src/App.tsx` and change `SERVER_URL` to your JARVIS server address:
```ts
const SERVER_URL = 'http://YOUR-PC-IP:3000';
```

### 3. Run on your phone

**iPhone (via Expo Go):**
```bash
npx expo start
```
- Download "Expo Go" app from App Store on your iPhone
- Scan the QR code shown in terminal with your iPhone camera
- JARVIS opens as a native app

**Android (via Expo Go):**
```bash
npx expo start
```
- Download "Expo Go" app from Play Store
- Scan the QR code with Expo Go app

**Web:**
```bash
npx expo start --web
```
- Opens in your browser at localhost:8081

### 4. Build standalone app (no Expo Go needed)

**For iPhone (.ipa):**
```bash
npx eas build --platform ios
```
Then install via TestFlight or AltStore.

**For Android (.apk):**
```bash
npx eas build --platform android --profile preview
```
Downloads a .apk you can install directly.

**For Desktop (Electron):**
The PWA at http://localhost:3000 can be installed as a desktop app via Chrome.

## Features
- Voice conversation (speak and listen)
- Encrypted personal data
- Password-protected access
- Liquid glass UI design
- Music playback (opens YouTube)
- Personal memory (JARVIS remembers things about you)

## Network Note
Your phone must be able to reach your PC's server. Options:
1. Same WiFi network + open firewall port 3000
2. Use a tunnel (ngrok, cloudflare tunnel)
3. Deploy server to cloud (AWS, Railway, etc.)
