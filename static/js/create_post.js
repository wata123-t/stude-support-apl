//////////////////////////////////////////////////////////////////////////////////////////
// create_post.html
//////////////////////////////////////////////////////////////////////////////////////////



///////////////////////////////////////////////////////////////////////////////////////
//  ●カテゴリー追加機能
///////////////////////////////////////////////////////////////////////////////////////
document.getElementById('add-detail').addEventListener('click', function () {
    const container = document.getElementById('details-container');
    const newRow = container.firstElementChild.cloneNode(true);
    // 入力値をクリア
    newRow.querySelector('select').value = "";
    newRow.querySelector('input[type="number"]').value = "";
    container.appendChild(newRow);
});

document.getElementById('details-container').addEventListener('click', function (e) {
    if (e.target && e.target.classList.contains('remove-detail')) {
        // 最初の行は削除できないようにする
        if (this.children.length > 1) {
            e.target.closest('.detail-row').remove();
        } else {
            alert("最低1つの学習実績が必要です。");
        }
    }
});


///////////////////////////////////////////////////////////////////////////////////////
//  ●学習時間の合計計算
///////////////////////////////////////////////////////////////////////////////////////

document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('details-container');
    const totalDisplay = document.getElementById('total-duration');

    // 合計を計算する関数
    function calculateTotal() {
        let total = 0;
        // すべてのduration[]入力を取得して加算
        const inputs = container.querySelectorAll('input[name="duration[]"]');
        inputs.forEach(input => {
            const val = parseInt(input.value);
            if (!isNaN(val)) {
                total += val;
            }
        });
        totalDisplay.textContent = total;
    }

    // 入力値が変更された時に計算（イベント委譲を使用）
    container.addEventListener('input', function(e) {
        if (e.target.name === 'duration[]') {
            calculateTotal();
        }
    });

    // 削除ボタンが押された時の計算
    container.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-detail')) {
            // 削除処理の後に計算を実行（setTimeoutで削除完了を待つか、削除直前に呼び出し）
            setTimeout(calculateTotal, 0);
        }
    });

    // 「追加」ボタンが押された際も、一応初期状態を反映（任意）
    document.getElementById('add-detail').addEventListener('click', function() {
        calculateTotal();
    });
});




///////////////////////////////////////////////////////////////////////////////////////
//  ●参照データ追加機能（シンプル版）
///////////////////////////////////////////////////////////////////////////////////////
document.getElementById('add-reference').addEventListener('click', function () {
    const container = document.getElementById('reference-container');
    const firstRow = container.querySelector('.reference-row');
    
    // 複製
    const newRow = firstRow.cloneNode(true);

    // 入力値のリセットと属性の整理
    newRow.querySelectorAll('input, select').forEach(element => {
        // 値をクリア
        if (element.tagName === 'SELECT') {
            // おすすめ度(ref_rating)の場合のみ、初期値を3(★★★)にする
            if (element.name === 'ref_rating') {
                element.value = "3";
            } else {
                element.selectedIndex = 0; 
            }
        } else {
            element.value = "";
        }
        
        // 【重要】IDが重複すると不具合の元になるため削除（または一意にする）
        if (element.id) {
            element.id = ""; 
        }
        
        // name属性はHTMLに書いた固定値（ref_title, ref_url, ref_category_idなど）のまま維持
        // 数字を付け加える処理は不要なので削除しました
    });

    container.appendChild(newRow);
});

// 削除処理
document.getElementById('reference-container').addEventListener('click', function (e) {
    if (e.target && e.target.classList.contains('remove-reference')) {
        const rows = this.querySelectorAll('.reference-row');
        if (rows.length > 1) {
            e.target.closest('.reference-row').remove();
        } else {
            // 削除せずに値をクリアするだけでもOK
            alert("これ以上削除できません。");
        }
    }
});

