//////////////////////////////////////////////////////////////////////////////////////////
// readmore.html
//////////////////////////////////////////////////////////////////////////////////////////
document.querySelectorAll('.like-button').forEach(button => {
    button.addEventListener('click', async (e) => {
        const postId = button.dataset.postId;
        const icon = button.querySelector('i');
        const countSpan = button.querySelector('.like-count');

        try {
            const response = await fetch(`/post/${postId}/like`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();

            if (data.status === 'success') {
                // ハートの形と色を切り替え
                if (data.action === 'liked') {
                    icon.classList.replace('bi-heart', 'bi-heart-fill');
                    icon.classList.replace('text-secondary', 'text-danger');
                } else {
                    icon.classList.replace('bi-heart-fill', 'bi-heart');
                    icon.classList.replace('text-danger', 'text-secondary');
                }
                // カウントの更新
                countSpan.textContent = data.like_count;
            }
        } catch (error) {
            console.error('Error:', error);
        }
    });
});