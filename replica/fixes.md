# ما يكرهه مستخدمو TikTok، وما يطلبونه، وما لم يُحل بعد

**العيّنة:** 648 عنصرًا من 3 مصادر: 200 مراجعة App Store من المتجر الأمريكي، 200 من المتجر الإماراتي (خلاصة المتجر السعودي رجعت فارغة من Apple، فاستُخدم الإماراتي كأقرب سوق عربي)، و249 تعليقًا من Hacker News. التاريخ: 2026-11-04.
**ما لم يُجمع:** Reddit رفض البحث غير المصادق (403). Google Play وG2 وCapterra وTrustpilot لا تملك خلاصات رسمية فلم تُقرأ. HN مصدر ضعيف هنا: أغلب تعليقاته نقاش سياسي/خصوصية يذكر TikTok عرضًا، لا شكاوى منتج.
**تحيّز العيّنة (مهم):** خلاصة Apple تعطي الأحدث أولًا، فـ207 من 400 مراجعة من 1–2 نوفمبر 2026 و93 من أكتوبر، والباقي يونيو/يوليو. موجتان تهيمنان: موجة «أين تحديث البانر» في المتجر الأمريكي، وحملة سعودية منسّقة في المتجر الإماراتي (#حملة_مقاطعة_التيك_توك، 19–28 أكتوبر). كلاهما حقيقي، لكن ليسا مراجعات مستقلة.
**حقيقة مقاسة خارج العيّنة (Apple lookup API، 2026-11-04):** تقييم TikTok في المتجر السعودي 3.67 من 2.78 مليون تقييم، مقابل 4.72 في الأمريكي من 18.4 مليون. حجم التطبيق 1,080 ميغابايت، الحد الأدنى iOS 15.

الملفات: `reviews.csv` (الخام)، `feedback.md` (الترتيب الآلي)، `themes-tiktok.json` (الموضوعات المخصصة)، `features.csv` (صفوف الإصلاحات).

## 1. ما يكرهونه

| # | المشكلة | مراجعات المتجر (منخفضة التقييم) | HN | المصادر | الثقة |
|---|---|---|---|---|---|
| 1 | حذف محتوى بريء، مخالفات وحظر «بلا سبب»، وبدون شرح | 49 (44) | 48 | 3 | قوية |
| 2 | التحديثات تصل لبعض المستخدمين دون غيرهم («أين البانر») | 106 (44) | 2 | 3 | قوية لكنها موجة أسبوع واحد |
| 3 | تحيّز مُدرك ضد المحتوى السعودي/العربي | 42 (38) | 4 | 3 | حقيقية لكنها حملة منسّقة؛ مدعومة بفارق التقييم السعودي |
| 4 | بلاغات عن إساءة واضحة ترجع «لا مخالفة» | 24 (20) | 15 | 3 | قوية |
| 5 | انهيار التطبيق على iPad وiOS 15، وحجمه الضخم | 37 (27) | 12 | 3 | قوية |
| 6 | قيود الرسائل والتعليقات وميزات تختفي | 40 (22) | 27 | 3 | متوسطة (موضوع واسع) |
| 7 | إعلانات كل ~3 مقاطع ومسلسلات AI قصيرة في الـFYP | 13 (11) | 26 | 3 | متوسطة، متصاعدة |
| 8 | الاستئناف والدعم لا يصلان لإنسان | 17 (13) | 10 | 3 | متوسطة |
| 9 | قفل العمر خاطئ وشاشة «احذف/أبقِ الحساب» لا تعمل | 10 (9) | 0 | 2 | **ضعيفة عدديًا** لكن حادة |
| 10 | انهيار المشاهدات/shadowban بلا تفسير | 13 (8) | 11 | 3 | متوسطة |

اقتباسات حرفية مرتبطة:

- "Constantly removing innocent videos for violating guidelines for no reason. This app was amazing two years ago now it is incorrectly removing innocent videos of makeup tutorial and reviews while keeping questionable videos that really require moderation un touched" (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=1/id=835599320/sortBy=mostRecent/json#14733188202
- "Wrongly accused of impersonation and not being able to appeal .. my account (aubpytt) was falsely flagged for impersonation. I’m an editor for a teen who sadly passed away, and I make awareness edits to keep her memory alive." (app-store-us, 1★) https://itunes.apple.com/us/rss/customerreviews/page=2/id=835599320/sortBy=mostRecent/json#14743047805
- "Im extremely disappointed with tiktok reporting system, almost every time i reported clear violation the same response being received “doesn’t violate our community guidelines “!!" (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=3/id=835599320/sortBy=mostRecent/json#14707374500
- "Tiktok does nothing about bots and fake pages. There is no option to help report fake pages of other people unless they are a celebrity" (app-store-us, 2★) https://itunes.apple.com/us/rss/customerreviews/page=1/id=835599320/sortBy=mostRecent/json#14743409957
- "نطالب بالعدالة والشفافية واحترام المستخدم السعودي، وتوضيح أسباب حذف المقاطع وإيقاف الحسابات، وتطبيق القواعد على الجميع دون تمييز." (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=3/id=835599320/sortBy=mostRecent/json#14714101131
- "أتمنى من إدارة تيك توك مراجعة قرارات حذف هذه المقاطع وتطبيق السياسات بعدل وشفافية، وعدم الخلط بين التعبير الوطني السلمي والمحتوى المخالف." (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=1/id=835599320/sortBy=mostRecent/json#14721252965
- "it just feels like everyone has different version of tiktok. I don’t have the banner update, I don’t have the option to do voice memos, and some people don’t even have the pronoun update" (app-store-us, 3★) https://itunes.apple.com/us/rss/customerreviews/page=2/id=835599320/sortBy=mostRecent/json#14743159527
- "I got banned for being under 13 when I’m clearly over 13 and post myself. I appealed and it confirmed my real age only to proceed to say I needed to take further action. The options were to delete my account or keep my account, obviously I wanted to keep it. But it wouldn’t let me press a THING" (app-store-us, 1★) https://itunes.apple.com/us/rss/customerreviews/page=1/id=835599320/sortBy=mostRecent/json#14743742737
- "Every time I contact support, I am told to edit my date of birth. However, when I explain that I am unable to change my date of birth, I either receive the same instructions again or an automated response that does not address my issue." (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=10/id=835599320/sortBy=mostRecent/json#14197310675
- "Im using ipad 15.8.8 smth and wen i updated my tiktok,it stopped working like,it will be on the logo screen for a few seconds and just not work" (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=10/id=835599320/sortBy=mostRecent/json#14189653213
- "App size 1.05Gb ?? Spy?. What’a inside? A communist spy program?" (app-store-us, 1★) https://itunes.apple.com/us/rss/customerreviews/page=3/id=835599320/sortBy=mostRecent/json#14741216298
- "Recently, I’m getting an advertisement after almost every 3 videos on my For You page. It makes the app much less enjoyable to use and interrupts the experience significantly." (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=9/id=835599320/sortBy=mostRecent/json#14229717781
- "It is sad to see how fast this app has fill with AI drama shows, I have blocked over 100 of these accounts but they make more every day and TikTok has made it difficult to block AI or report AI" (app-store-us, 1★) https://itunes.apple.com/us/rss/customerreviews/page=3/id=835599320/sortBy=mostRecent/json#14742398772
- "Every update I will have a feature I use constantly just completely gets taken away. I can no longer send comments in dms and I haven’t been able to since the newest update." (app-store-us, 1★) https://itunes.apple.com/us/rss/customerreviews/page=9/id=835599320/sortBy=mostRecent/json#14738396374
- "my first videos used to get 5,000, 10,000, 40,000, 100,000 views, now my videos are getting 5 or 10 views, please check my account and tell me what is the problem with my account" (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=10/id=835599320/sortBy=mostRecent/json#14189556064

## 2. ما يطلبونه بالاسم (كلها صغيرة ورخيصة)

- حذف عدة رسائل دفعة واحدة: "You should be able to delete more messages at one’s" (app-store-ae, 2★) https://itunes.apple.com/ae/rss/customerreviews/page=9/id=835599320/sortBy=mostRecent/json#14214821101
- إلغاء متابعة الحسابات الخاملة دفعة واحدة: "users should be able to filter accounts that haven’t posted in the last 6 months, 1 year, or any custom timeframe, then select all of them and unfollow them with a single tap." (app-store-ae, 5★) https://itunes.apple.com/ae/rss/customerreviews/page=9/id=835599320/sortBy=mostRecent/json#14251035069
- مسح كل الإعادات (reposts) بضغطة: "a button that allows users to remove or clear all reposts at once." (app-store-ae, 4★) https://itunes.apple.com/ae/rss/customerreviews/page=10/id=835599320/sortBy=mostRecent/json#14191051741
- ملصقات في التعليقات: "لماذا ليس لدينا خاصية ارسال الملصقات ب التعليقات" (app-store-ae, 1★) https://itunes.apple.com/ae/rss/customerreviews/page=10/id=835599320/sortBy=mostRecent/json#14183121083
- مدة الصورة في المحرر: "What happened to being able to edit videos where you want an image to be a certain length of time to match the music? I can’t do that anymore." (app-store-us, 1★) https://itunes.apple.com/us/rss/customerreviews/page=2/id=835599320/sortBy=mostRecent/json#14742971233
- صورة داخل صورة: "Bring back Picture in Picture so I can maximize my multitasking" (app-store-us, 3★) https://itunes.apple.com/us/rss/customerreviews/page=9/id=835599320/sortBy=mostRecent/json#14738221580
- إعادة توجيه التعليقات: "Верните функцию пересылки комментариев" (app-store-us, 3★) https://itunes.apple.com/us/rss/customerreviews/page=9/id=835599320/sortBy=mostRecent/json#14738698677
- بث الألعاب من الجوال إلى الاستديو على Mac: "There is still no option in Tiktok live studio to cast wireless/wirelessly from your iPhone." (app-store-ae, 3★) https://itunes.apple.com/ae/rss/customerreviews/page=9/id=835599320/sortBy=mostRecent/json#14231855782
- حد المتابعة بالساعة يمنع رد المتابعة: "أرجو حل مشكلة عدم القدرة على المتابعة أو رد المتابعة عند القيام بمتابعة الكثير من الأشخاص في وقت محصور" (app-store-ae, 2★) https://itunes.apple.com/ae/rss/customerreviews/page=10/id=835599320/sortBy=mostRecent/json#14178965324

كل طلب أعلاه بمراجعة واحدة أو اثنتين: **ضعيف** كاتجاه، لكنه رخيص كتمييز.

## 3. ما لم يُحل (وظائف كاملة أو فئات يتجاهلها التطبيق)

1. **المستخدم العربي/الخليجي يُراجَع بقواعد ومراجعين لا يفهمون سياقه.** 42 مراجعة في 10 أيام + فارق تقييم المتجر السعودي (3.67 مقابل 4.72). الحملة منسّقة، لكن فارق التقييم على ملايين التقييمات ليس حملة. استنتاج قوي، ليس حقيقة مؤكدة.
2. **لا أحد يشرح قرار الإشراف ولا يوجد إنسان في نهاية الاستئناف.** يظهر في كل المصادر وكل الفترات (يونيو، أكتوبر، نوفمبر). هذا الاتجاه الأكثر ثباتًا في العيّنة.
3. **الآباء والقاصرون: بوابة العمر تفشل في الاتجاهين.** تحظر من هم فوق 13 خطأً، وتترك أطفالًا يبثون. 10 مراجعات فقط، لكنها كلها تصف الفشل نفسه.
4. **من يريد خلاصة بلا إعلانات كل 3 مقاطع وبلا محتوى AI.** بدأ يظهر بقوة في نوفمبر 2026 مع «المسلسلات القصيرة».

## 4. خطة الإصلاح (مرتّبة بالأدلة × رخص التنفيذ)

| # | ماذا نبني | الحجم | المهارة | الدليل |
|---|---|---|---|---|
| 1 | **قرار إشراف شفاف:** كل حذف يعرض القاعدة بالضبط والمقطع/الثانية المخالفة ونسخة عربية مفهومة | M | replica-backend + build | موضوع 1 (49 متجر/44 منخفضة) |
| 2 | **استئناف بشري بتذكرة ظاهرة في التطبيق** مع مهلة معلنة وحالة تتبّع | M | replica-backend | موضوع 8 (17) + موضوع 1 |
| 3 | **بلاغ له نتيجة مفسّرة** وتصعيد ثانٍ، وبلاغ انتحال لأي شخص لا للمشاهير فقط | S | replica-backend + build | موضوع 4 (24) |
| 4 | **بوابة عمر لا تنتهي بطريق مسدود:** مسار تحقق واضح (هوية/ولي أمر)، ولا شاشة «احذف/أبقِ» بلا أزرار تعمل | M | replica-backend | موضوع 9 (10، ضعيف عدديًا لكن حاد) |
| 5 | **نسخة واحدة للجميع:** لا feature flags بالفئة، وسجل تغييرات داخل التطبيق | S | replica-build + deploy | موضوع 2 (106، موجة) |
| 6 | **تطبيق خفيف:** هدف أقل من 150 MB ودعم لائق لـiPad وiOS القديم | M | replica-architect + build | موضوع 5 (37)؛ الأصل 1,080 MB |
| 7 | **تحكم في الإعلانات ووسم محتوى AI** مع مفتاح «أخفِ محتوى AI» وحد أقصى معلن للإعلانات | M | replica-build + backend | موضوع 7 (13 متجر + 26 HN) |
| 8 | **إشراف عربي أصيل مع شفافية إقليمية:** مراجعون ناطقون بالعربية ونشر إحصاءات الإنفاذ لكل منطقة | L | replica-backend + launch | موضوع 3 (42) + فارق تقييم المتجر السعودي |

لا شكاوى تسعير ذات وزن (التطبيق مجاني)؛ لا شيء يُحال إلى replica-launch من هذا الباب.

## 5. الزاوية (ثلاث خيارات، التوصية الأولى)

1. **(موصى بها)** للمبدعين والمستخدمين في السعودية والخليج الذين يُحذف محتواهم بلا سبب مفهوم ولا يجدون من يرد، {{التطبيق}} يشرح كل قرار بالعربية ويضع إنسانًا في نهاية كل استئناف خلال مهلة معلنة.
   الدليل: موضوعات 1 و3 و8، 108 مراجعات عبر 3 مصادر، وتقييم 3.67 في المتجر السعودي.
2. للأهالي الذين يريدون فيديو قصيرًا لا يحظر ابنهم ذا الـ14 خطأً ولا يترك ابن الـ9 يبث، {{التطبيق}} يتحقق من العمر مرة واحدة وبوضوح ثم يحترمه.
   الدليل: موضوع 9، 10 مراجعات عبر مصدرين. **ضعيف** عدديًا.
3. لمن سئم إعلانًا كل ثلاث مقاطع ومسلسلات AI، {{التطبيق}} يعلن حدّ الإعلانات ويسمح بإخفاء محتوى AI.
   الدليل: موضوع 7، 39 عبر 3 مصادر.

**سبب الترجيح:** الخيار 1 هو الوحيد المدعوم باتجاه ثابت عبر الفترات الثلاث وبرقم خارج العيّنة، وهو الوحيد الذي يعطي سببًا للانتقال من شبكة قائمة. الخياران 2 و3 ميزات، لا منتج.

## الحكم الصريح قبل الخطوة التالية

- **لا تستنسخ TikTok كتطبيق عام.** خندقه هو الشبكة والكتالوج وخوارزمية التوصية، وهذه الثلاثة تحديدًا مما تستثنيه المهارة. 74 تعليقًا في HN تذكر بدائل بالاسم (Reels، Shorts، Loops، Rednote...) والناس يعرفونها ولا ينتقلون.
- **الفجوة الحقيقية الوحيدة:** مجتمع فيديو قصير إقليمي بإشراف عربي شفاف واستئناف بشري. هذه مشكلة شبكة ذات طرفين وانطلاقة باردة؛ حجمها L على الأقل، ولا يحلها الكود وحده.
- إذا استمررت، شغّل `/replica-recon` على شريحة ضيقة فقط: الخلاصة، النشر، التعليقات، البلاغ والاستئناف. لا LIVE، لا هدايا، لا متجر.

التالي: `/replica-brand` فقط إذا قررت المضي في الزاوية 1.
