# iOS visual review

For visible iOS changes, run the appropriate private simulator preview without waiting for the user to ask for screenshots. Download and actually inspect every image listed in capture-index.json. Use the images to check the requested screens and states, fix defects, and recapture after fixes. An empty or wrong screen is not sufficient evidence for a populated state.

Only after inspecting the images, record findings with scripts/ios/visual_review.py record, including reviewer, scope, notes, and each --reviewed-image. The record command uploads an attestation; it does not perform image analysis. Never approve images you have not viewed. If images cannot be inspected, report the limitation and leave the review pending.

Before IPA delivery, pass the private preview release tag in reviewed_preview. The workflow rejects missing reviews, failed preview runs, changed archives, and reviews from another app commit before starting the Mac build. Changed code requires a fresh preview and review. Full regression tests remain required. Keep screenshots and review notes private. No automatic IPA scheduling.
