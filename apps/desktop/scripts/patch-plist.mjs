/**
 * patch-plist.mjs
 * Runs after `tauri build` to inject macOS privacy permission strings
 * into the bundled Info.plist (Tauri v1 does not support this natively).
 */
import { execSync } from "child_process";
import { existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const plist = resolve(__dirname, "../src-tauri/target/release/bundle/macos/Lani.app/Contents/Info.plist");

if (!existsSync(plist)) {
  console.error("❌ Info.plist not found at:", plist);
  process.exit(1);
}

const entries = {
  NSMicrophoneUsageDescription: "Lani needs microphone access for voice commands and speech recognition.",
  NSCameraUsageDescription:     "Lani needs camera access for screen capture features.",
  NSAppleEventsUsageDescription: "Lani needs automation access to control apps on your Mac.",
};

for (const [key, value] of Object.entries(entries)) {
  try {
    execSync(`/usr/libexec/PlistBuddy -c "Add :${key} string '${value}'" "${plist}" 2>/dev/null || /usr/libexec/PlistBuddy -c "Set :${key} '${value}'" "${plist}"`, { stdio: "inherit" });
    console.log(`✅ ${key}`);
  } catch (e) {
    console.warn(`⚠️  Could not set ${key}: ${e.message}`);
  }
}

console.log("✅ Info.plist patched with privacy permissions.");
