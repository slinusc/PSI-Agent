// Override the "Create New Chat" confirmation dialog
(function() {
    console.log('Custom Chainlit JS loaded - v2');

    // Method 1: Override window.confirm
    const originalConfirm = window.confirm;
    window.confirm = function(message) {
        console.log('window.confirm called with:', message);
        if (message && message.includes('clear your current chat history')) {
            console.log('Bypassing new chat confirmation (window.confirm)');
            return true;
        }
        return originalConfirm.call(this, message);
    };

    // Method 2: Use MutationObserver to auto-click confirmation buttons IMMEDIATELY
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            mutation.addedNodes.forEach(function(node) {
                if (node.nodeType === 1) { // ELEMENT_NODE
                    // Look for dialog/modal elements
                    const dialogs = node.querySelectorAll ?
                        [node, ...node.querySelectorAll('[role="dialog"], [role="alertdialog"], .MuiDialog-root')] :
                        [node];

                    dialogs.forEach(function(dialog) {
                        const text = dialog.textContent || '';
                        if (text.includes('clear your current chat history') ||
                            (text.includes('Create New Chat') && text.includes('Are you sure'))) {
                            console.log('Found new chat confirmation dialog, hiding and auto-confirming...');

                            // Hide the dialog immediately
                            dialog.style.display = 'none';

                            // Find parent backdrop/overlay and hide it too
                            let parent = dialog.parentElement;
                            while (parent) {
                                if (parent.classList && (
                                    parent.classList.contains('MuiBackdrop-root') ||
                                    parent.classList.contains('MuiModal-root') ||
                                    parent.style.position === 'fixed'
                                )) {
                                    parent.style.display = 'none';
                                }
                                parent = parent.parentElement;
                            }

                            // Try to find and click the confirm button immediately
                            const buttons = dialog.querySelectorAll('button');
                            buttons.forEach(function(btn) {
                                const btnText = (btn.textContent || '').toLowerCase();
                                if (btnText.includes('yes') || btnText.includes('continue') || btnText.includes('confirm')) {
                                    console.log('Auto-clicking confirm button');
                                    btn.click(); // Click immediately, no delay
                                }
                            });
                        }
                    });
                }
            });
        });
    });

    // Start observing when DOM is ready
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
        console.log('MutationObserver installed');
    } else {
        window.addEventListener('DOMContentLoaded', function() {
            observer.observe(document.body, { childList: true, subtree: true });
            console.log('MutationObserver installed (after DOMContentLoaded)');
        });
    }

    console.log('Confirm override installed');
})();
