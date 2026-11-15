# अपने डिवाइस जोड़ना

[English](clients.md) · हिन्दी · [বাংলা](clients.bn.md)

पहले आधिकारिक **WireGuard** ऐप इंस्टॉल करें, फिर Setu से मिला कॉन्फ़िग इम्पोर्ट करें।

| डिवाइस | ऐप | इम्पोर्ट कैसे करें |
|---|---|---|
| iPhone / iPad | WireGuard (App Store) | **+ > Create from QR code**, फिर `setu add` का QR स्कैन करें |
| Android | WireGuard (Play Store, F-Droid) | **+ > Scan from QR code** |
| macOS | WireGuard (Mac App Store) | **Import tunnel(s) from file** (`setu show NAME --out NAME.conf`) |
| Windows | wireguard.com/install | **Import tunnel(s) from file** |
| Linux | `sudo apt install wireguard` | `sudo cp NAME.conf /etc/wireguard/ && sudo wg-quick up NAME` |

## किसी दोस्त या परिवार वाले को भेजना

`setu card NAME --lang hi` एक सादा HTML पेज बनाता है जिसमें QR कोड और हिन्दी में 3 आसान स्टेप होते हैं। इसे सीधे WhatsApp या Signal पर भेज दें। इस फ़ाइल में डिवाइस की चाबी होती है, इसलिए इसे सिर्फ़ उसी व्यक्ति को भेजें और बाद में डिलीट कर दें।

## काम की बातें

- एक डिवाइस के लिए एक कॉन्फ़िग। एक ही कॉन्फ़िग दो डिवाइस पर न चलाएँ, वे एक-दूसरे को बाहर कर देंगे।
- चेक करने के लिए <https://ifconfig.me> खोलें। उसमें आपके सर्वर का IP दिखना चाहिए।
- iOS पर **On-demand** और Android पर **Always-on VPN** चालू करें ताकि टनल अपने-आप दोबारा चालू हो जाए।
- फ़ोन खो गया? `setu remove NAME` चलाएँ। उसका कॉन्फ़िग तुरंत बंद हो जाता है।
- मेहमान के लिए: `setu add guest --expires 3` तीन दिन बाद अपने-आप हट जाता है।
- कुछ गड़बड़ हो तो `setu doctor` चलाएँ, या [समस्या समाधान](troubleshooting.md) देखें।
