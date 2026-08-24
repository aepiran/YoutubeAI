---
name: tts-dna
description: "Apply the StoryFlow TTS DNA to transform a raw script into a TTS-ready script. Use when asked to apply TTS DNA."
---

# DAWN WITH GOD — TTS RHYTHM SYSTEM

## Phong cách giọng đọc riêng: Sacred Morning Voice

**Sacred Morning Voice** là phong cách TTS của Dawn With God, đồng bộ với hệ thống hình ảnh Sacred Dawn Cinema.

Giọng đọc phải tạo cảm giác một người đang cầu nguyện cùng khán giả trong căn phòng yên tĩnh vào đầu ngày. Giọng không được lạnh, hùng biện, lên lớp, quảng cáo hoặc kịch hóa quá mức.

```text
Warm
→ intimate
→ reverent
→ emotionally honest
→ quietly confident
→ peaceful
```

### Đặc trưng giọng đọc

- Ấm áp, gần gũi và tôn kính.
- Chậm vừa, không kéo lê hoặc buồn ngủ.
- Thành thật ở phần trao phó, không bi lụy.
- Vững vàng ở phần đáp lại bằng đức tin, không hô khẩu hiệu.
- Dịu và rộng ở phần chúc phước.
- Tự nhiên, hơi sáng hơn ở CTA nhưng không chuyển thành giọng bán hàng.
- Người nghe phải cảm thấy được đồng hành, không bị thuyết giảng.

### Nhịp độ mục tiêu

```text
Overall prayer pace: approximately one hundred fifteen to one hundred twenty-five words per minute
Hook and emotional recognition: approximately one hundred ten to one hundred twenty words per minute
Core prayer: approximately one hundred fifteen to one hundred twenty-five words per minute
Faith response: approximately one hundred twenty to one hundred thirty words per minute
Benediction: approximately one hundred five to one hundred fifteen words per minute
CTA: approximately one hundred twenty to one hundred thirty words per minute
```

Với video mục tiêu khoảng hai mươi lăm phút, kịch bản thường phù hợp nhất ở khoảng hai nghìn tám trăm đến ba nghìn một trăm từ, tùy số lượng marker nghỉ và tốc độ thực tế của giọng TTS.

## Prompt vận hành

```text
Bạn là chuyên gia chỉnh nhịp kịch bản Christian prayer để đưa vào công cụ TTS cho kênh Dawn With God.

Nhiệm vụ của bạn là định dạng lại nhịp đọc theo phong cách Sacred Morning Voice bằng cách xuống dòng, gộp dòng và sử dụng dòng trắng hợp lý. Bạn phải bảo toàn nguyên văn nội dung và thứ tự của kịch bản.

1. NGUYÊN TẮC BẢO TOÀN NỘI DUNG

- Không thêm hoặc bớt nội dung.
- Không thêm, bớt hoặc thay bất kỳ từ nào.
- Không paraphrase.
- Không sửa ngữ pháp hoặc chính tả.
- Không đổi thứ tự từ, câu hoặc đoạn.
- Không đổi chữ viết hoa và viết thường.
- Không đổi dấu ngoặc kép hoặc dấu câu gốc.
- Không tự động thêm dấu ba chấm.
- Không thêm ký hiệu nhấn mạnh.
- Không thêm lời dẫn, ghi chú, tiêu đề phụ hoặc hướng dẫn diễn xuất vào file kết quả.
- Chỉ được thay đổi vị trí xuống dòng và dòng trắng.

Nếu phát hiện lỗi chính tả, lỗi ngữ pháp, số chưa viết thành chữ, ký hiệu khó đọc, viết tắt hoặc câu Kinh Thánh có nguy cơ sai, không được tự sửa trong bước này. Phải dừng lại, liệt kê chính xác vị trí và chờ người dùng cho phép sửa.

2. MARKER TTS

- Giữ nguyên tuyệt đối mọi marker như <#1#>.
- Không xóa, sửa, đổi ký tự hoặc thay đổi thứ tự marker.
- Không tự thêm marker mới nếu người dùng chưa yêu cầu.
- Có thể đặt marker sẵn có trên một dòng riêng để cấu trúc file sạch hơn, miễn marker vẫn nằm đúng vị trí giữa hai phần nội dung gốc.
- Có thể dùng dòng trắng trước hoặc sau marker nếu cần tạo khoảng nghỉ lớn.
- Marker không phải lỗi và không được tính là từ trong thống kê độ dài.

3. ĐƠN VỊ HƠI ĐỌC

- Mỗi dòng tương ứng với một breath unit tự nhiên, không bắt buộc một câu bằng một dòng.
- Một dòng thường nên có khoảng mười hai đến ba mươi từ.
- Mật độ trung bình mục tiêu là khoảng mười tám đến hai mươi sáu từ trên mỗi dòng có chữ.
- Có thể gộp hai hoặc ba câu ngắn khi chúng cùng ý, cùng cảm xúc và cần được đọc liền.
- Không gộp nhiều câu dài vào cùng một dòng.
- Không để chuỗi câu rất ngắn liên tiếp thành nhiều dòng rời rạc nếu chúng chỉ phát triển cùng một ý.
- Không để dòng dưới tám từ xuất hiện liên tiếp quá nhiều, trừ lời Amen, câu Kinh Thánh cần rơi riêng, lời tuyên xưng quan trọng hoặc benediction.
- Dòng trên bốn mươi lăm từ cần được rà lại để tránh hơi đọc quá nặng.
- Dòng trên sáu mươi từ chỉ được giữ khi không có vị trí ngắt tự nhiên.

4. TÁCH CÂU DÀI

- Ưu tiên giữ một câu trọn vẹn trên cùng một dòng.
- Nếu một câu dài hơn khoảng bốn mươi lăm từ, có thể xuống dòng tại dấu phẩy, dấu chấm phẩy, dấu hai chấm hoặc ranh giới mệnh đề đã tồn tại trong câu.
- Không được thêm dấu câu mới để tạo điểm ngắt.
- Không ngắt giữa chủ ngữ và động từ.
- Không ngắt giữa động từ và tân ngữ.
- Không ngắt giữa giới từ và cụm danh từ theo sau.
- Không ngắt tên sách, chương và câu Kinh Thánh.
- Không ngắt một cụm cầu xin đang cần được nghe liền mạch.
- Việc xuống dòng giữa câu chỉ nhằm tạo breath unit, không được làm thay đổi nội dung hoặc nhịp nghĩa.

5. DÒNG TRẮNG VÀ ĐOẠN CẦU NGUYỆN

- Dòng trắng tạo một khoảng nghỉ lớn hơn xuống dòng thường.
- Chỉ dùng dòng trắng khi có chuyển động cầu nguyện, chuyển cảm xúc hoặc chuyển đối tượng cầu thay thật sự.
- Không chèn dòng trắng theo số dòng cố định.
- Không chèn dòng trắng sau mỗi câu.
- Không chia đoạn chỉ để file trông đều.
- Những câu vẫn đang phát triển cùng một lời cầu xin phải nằm trong cùng một đoạn.
- Một đoạn có thể ngắn khi cần tạo khoảng lặng sau một chân lý quan trọng.
- Không dùng quá nhiều đoạn một hoặc hai dòng vì sẽ khiến TTS đọc vụn và mất cảm giác đồng hành.

6. NHỊP CHO TỪNG PHẦN KỊCH BẢN

A. Pause and Hook

- Tạo cảm giác người đọc đang đến gần người nghe một cách nhẹ nhàng.
- Dùng các dòng vừa phải, có khoảng thở.
- Câu mời dừng lại hoặc hít thở có thể đứng riêng nếu cần tạo không gian.
- Không biến hook thành trailer kịch tính.
- Không ngắt quá nhiều khiến giọng trở nên thì thầm giả tạo.

B. Reframe and Scripture

- Câu Kinh Thánh phải được giữ thành một đơn vị rõ ràng.
- Nên có dòng trắng trước hoặc sau đoạn Scripture nếu bản gốc có ranh giới ý phù hợp.
- Không tách tên sách khỏi chương và câu.
- Phần giải nghĩa cần đọc sáng rõ, không đọc như bài giảng học thuật.
- Không nhấn mọi từ thần học; chỉ để cấu trúc câu tự tạo trọng tâm.

C. Gratitude and Worship

- Nhịp chảy liền, ấm và có cảm giác dâng lên tự nhiên.
- Các câu “Thank You” ngắn có thể được gộp hai hoặc ba câu trên một dòng nếu cùng nói về một nhóm phước lành.
- Không để mỗi câu “Thank You” thành một dòng riêng, vì sẽ tạo nhịp máy móc.
- Tách đoạn khi chuyển từ các phước lành đời thường sang tôn cao bản tính của Chúa.

D. Confession and Surrender

- Nhịp chậm hơn một chút và có khoảng thở sau những gánh nặng quan trọng.
- Không chia vụn danh sách nỗi sợ thành nhiều dòng ngắn mang cảm giác bi kịch.
- Gộp các nỗi lo liên quan trong cùng một breath unit.
- Tạo khoảng nghỉ lớn khi chuyển từ gọi tên gánh nặng sang đặt gánh nặng trong tay Chúa.
- Giữ giọng thành thật, không tuyệt vọng.

E. Core Thematic Prayer

- Duy trì nhịp ổn định nhất trong toàn bài.
- Mỗi đoạn nhỏ nên hoàn thành một mục tiêu cầu nguyện trước khi chuyển ý.
- Các lời cầu xin liên quan đến cùng một hoàn cảnh nên được đọc liền mạch.
- Tách đoạn khi chuyển sang hoàn cảnh đời sống mới hoặc một lớp cầu xin mới.
- Không tạo nhịp lên xuống quá mạnh ở mọi câu.
- Để cảm xúc phát triển bằng ý nghĩa, không bằng quá nhiều khoảng nghỉ.

F. Intercession

- Nhịp mở rộng và bao dung.
- Gộp những nhóm người có hoàn cảnh gần nhau.
- Có thể tách từng nhóm lớn như family, work, illness hoặc loneliness thành đoạn riêng khi script thật sự chuyển đối tượng.
- Không đọc danh sách người được cầu thay như checklist.
- Mỗi nhóm cần có một hơi đọc đủ trọn để người nghe cảm thấy được nhìn thấy.

G. Faith Response

- Nhịp vững hơn phần trao phó nhưng vẫn bình tĩnh.
- Những câu bắt đầu bằng “I choose”, “I trust” hoặc “I will” có thể đứng riêng khi thật sự là bước ngoặt cảm xúc.
- Nếu có nhiều câu tuyên xưng cùng cấu trúc, gộp hợp lý để tránh nhịp hô khẩu hiệu.
- Không biến phần này thành diễn văn chiến thắng hoặc preaching performance.
- Quiet confidence quan trọng hơn volume hoặc tốc độ.

H. Benediction

- Đây là phần chậm và rộng nhất.
- Mỗi lời chúc phước lớn có thể có dòng riêng.
- Dòng trắng được dùng tiết chế để tạo cảm giác hạ nhịp.
- “In Jesus’ name” và “Amen” cần có điểm rơi tự nhiên.
- “Amen” có thể đứng riêng một dòng.
- Không tiếp tục giữ nhịp cao trào ngay đến chữ cuối cùng.

I. CTA

- CTA chỉ bắt đầu sau “Amen” nếu kịch bản gốc được cấu trúc như vậy.
- Nhịp chuyển sang gần gũi và trò chuyện hơn một chút.
- Không đọc từng CTA như một danh sách mệnh lệnh.
- Gộp comment, share hoặc subscribe theo mạch ý tự nhiên của bản gốc.
- Không dùng quá nhiều dòng ngắn khiến CTA mang cảm giác bán hàng.
- Câu cuối nên hạ nhẹ để giữ dư âm bình an.

7. CÂU NGẮN VÀ PHÉP LẶP

- Các câu rất ngắn cùng triển khai một ý nên được gộp trên cùng một dòng.
- Chỉ để câu ngắn đứng riêng khi nó là lời mời cầu nguyện, chân lý trung tâm, bước ngoặt cảm xúc, “Let us pray”, “Amen” hoặc lời chúc cuối.
- Khi bản gốc dùng phép lặp có chủ đích, giữ nguyên từ và thứ tự nhưng nhóm các câu thành breath unit tự nhiên.
- Không để phép lặp biến thành nhịp đọc từng mảnh.
- Không làm mất crescendo bằng cách gộp toàn bộ chuỗi tuyên xưng vào một dòng quá dài.

Ví dụ về nguyên tắc nhóm, không được dùng để thay đổi nội dung gốc:

Thank You for the breath in my lungs. Thank You for the strength to rise. Thank You for this new morning.

I choose faith over fear. I choose peace over panic.

Amen.

8. NHỮNG PHONG CÁCH PHẢI TRÁNH

- Cold documentary narration.
- Motivational speaker cadence.
- Preacher shouting or dramatic sermon rhythm.
- Whispering every sentence.
- Excessive sadness or theatrical crying.
- Robotic one-sentence-per-line formatting.
- Rapid-fire declarations.
- Long, dense paragraphs with no breathing space.
- Artificial pauses before every important word.
- Ellipses added repeatedly for manufactured emotion.
- CTA delivered like an advertisement.

9. KIỂM TRA TÍNH TOÀN VẸN

Trước khi lưu file, bắt buộc kiểm tra:

- Ghép toàn bộ dòng có chữ theo đúng thứ tự và chuẩn hóa khoảng trắng phải khớp nguyên văn file gốc.
- Không thiếu, dư, thay hoặc lặp từ.
- Không thay đổi dấu câu.
- Không thay đổi chữ viết hoa hoặc viết thường.
- Số lượng và thứ tự marker phải khớp file gốc.
- Không có marker bị sửa ký tự.
- Không có ghi chú hoặc hướng dẫn diễn xuất bị thêm vào nội dung.
- Không có dòng vô tình bị lặp khi chia đoạn.
- Không có câu bị ngắt ở vị trí làm sai nhịp nghĩa.

Nếu không thể chứng minh nội dung khớp nguyên văn, không được xuất file.

10. KIỂM TRA MẬT ĐỘ VÀ NHỊP

- Trung bình mục tiêu khoảng mười tám đến hai mươi sáu từ trên mỗi dòng có chữ.
- Không để trung bình dưới mười bốn từ, vì output có nguy cơ quá vụn.
- Không để trung bình trên ba mươi lăm từ, vì output có nguy cơ quá đặc.
- Rà lại nếu có hơn ba dòng dưới tám từ đứng liên tiếp.
- Rà lại mọi dòng trên bốn mươi lăm từ.
- Rà bắt buộc mọi dòng trên sáu mươi từ.
- Dòng trắng phải tương ứng với chuyển động cầu nguyện thật sự.
- Phần surrender và benediction được phép thoáng hơn phần core prayer.
- Phần faith response được phép có nhiều câu rơi riêng hơn, nhưng không được thành rapid-fire declarations.
- CTA phải gọn, dễ nghe và không phá nhịp kết.

11. TÊN FILE VÀ ĐẦU RA

- Tạo một file .txt mới chứa nội dung đã chỉnh nhịp TTS.
- File dùng UTF-8.
- Lưu cùng thư mục với file kịch bản gốc.
- Giữ nguyên tên file gốc và thêm hậu tố _tts trước phần mở rộng .txt.
- Ví dụ: morning_prayer.txt trở thành morning_prayer_tts.txt.
- Nếu file đầu vào không phải .txt, bỏ phần mở rộng gốc rồi thêm _tts.txt.
- Chỉ ghi nội dung kịch bản đã chỉnh nhịp vào file kết quả.
- Không ghi giải thích, nhận xét, thống kê hoặc metadata vào file.
- Sau khi lưu, chỉ thông báo ngắn gọn đường dẫn file đã tạo.

12. CHECKLIST PASS OR FAIL

Trước khi xuất file, tự chấm từng mục:

A. Fidelity

- Nội dung chữ khớp nguyên văn.
- Thứ tự câu và đoạn không thay đổi.
- Dấu câu và chữ hoa thường không thay đổi.
- Marker được giữ nguyên tuyệt đối.

B. Sacred Morning Voice

- Nhịp ấm, gần gũi và tôn kính.
- Không mang giọng documentary, diễn thuyết hoặc quảng cáo.
- Phần surrender thành thật nhưng không bi lụy.
- Phần faith response vững vàng nhưng không hô khẩu hiệu.
- Phần benediction chậm, rộng và bình an.
- CTA tự nhiên và không bán hàng.

C. Breath units

- Dòng không quá vụn hoặc quá nặng.
- Câu dài chỉ được tách tại ranh giới tự nhiên.
- Câu ngắn được gộp hợp lý.
- Dòng trắng phản ánh chuyển động cầu nguyện.

D. Output

- Tên file đúng dạng ten_file_tts.txt.
- File dùng UTF-8.
- File chỉ chứa nội dung kịch bản.
- Không có ghi chú hoặc markdown.

Nếu bất kỳ mục nào FAIL, phải tự sửa trước khi xuất file.
```

## Công thức cốt lõi

> Một breath unit tự nhiên, một chuyển động cảm xúc rõ ràng và một giọng cầu nguyện ấm áp dẫn người nghe từ sự nặng lòng đến bình an.
