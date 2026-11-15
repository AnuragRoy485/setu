# আপনার ডিভাইস যোগ করা

[English](clients.md) · [हिन्दी](clients.hi.md) · বাংলা

প্রথমে সরকারি **WireGuard** অ্যাপ ইনস্টল করুন, তারপর Setu থেকে পাওয়া কনফিগ ইমপোর্ট করুন।

| ডিভাইস | অ্যাপ | ইমপোর্ট করার উপায় |
|---|---|---|
| iPhone / iPad | WireGuard (App Store) | **+ > Create from QR code**, তারপর `setu add` এর QR স্ক্যান করুন |
| Android | WireGuard (Play Store, F-Droid) | **+ > Scan from QR code** |
| macOS | WireGuard (Mac App Store) | **Import tunnel(s) from file** (`setu show NAME --out NAME.conf`) |
| Windows | wireguard.com/install | **Import tunnel(s) from file** |
| Linux | `sudo apt install wireguard` | `sudo cp NAME.conf /etc/wireguard/ && sudo wg-quick up NAME` |

## বন্ধু বা পরিবারের কাউকে পাঠানো

`setu card NAME --lang bn` একটি সাধারণ HTML পাতা তৈরি করে, যাতে QR কোড আর বাংলায় তিনটি সহজ ধাপ থাকে। এটি সরাসরি WhatsApp বা Signal এ পাঠিয়ে দিন। ফাইলটিতে ডিভাইসের চাবি থাকে, তাই শুধু সেই মানুষটিকেই পাঠান এবং পরে মুছে ফেলুন।

## কাজের কথা

- একটি ডিভাইসের জন্য একটি কনফিগ। একই কনফিগ দুই ডিভাইসে চালাবেন না, তারা একে অপরকে বের করে দেবে।
- যাচাই করতে <https://ifconfig.me> খুলুন। সেখানে আপনার সার্ভারের IP দেখা উচিত।
- iOS এ **On-demand** আর Android এ **Always-on VPN** চালু করুন, যাতে টানেল নিজে থেকেই আবার চালু হয়।
- ফোন হারিয়ে গেছে? `setu remove NAME` চালান। তার কনফিগ সঙ্গে সঙ্গে বন্ধ হয়ে যায়।
- অতিথির জন্য: `setu add guest --expires 3` তিন দিন পর নিজে থেকেই মুছে যায়।
- কিছু গোলমাল হলে `setu doctor` চালান, অথবা [সমস্যা সমাধান](troubleshooting.md) দেখুন।
