# Recon map: TikTok (iOS، المتجر السعودي)

**النطاق:** شريحة ضيقة فقط: الخلاصة (For You/Following)، النشر، التعليقات، البلاغ، والاستئناف، مع الحد الأدنى من الهيكل (دخول، ملف شخصي، صندوق الإشعارات) اللازم لتشغيلها. **خارج النطاق:** LIVE، الهدايا والعملات، المتجر، الرسائل الخاصة، Duet/Stitch، مكتبة الأصوات والمؤثرات.
**لمن:** مجتمع فيديو قصير للسعودية والخليج بإشراف عربي شفاف واستئناف بشري (الزاوية 1 في `fixes.md`).
**التاريخ:** 2026-11-04
**القيود المطبقة:** مصادر عامة فقط. لم يُستخدم حساب المستخدم ولا متصفح، لم تُقرأ حزم JavaScript ولا واجهات خاصة. لقطات App Store العامة محفوظة في `replica/screens/` للمرجع فقط، مستثناة من Git ولن تُشحن.

## المصادر

| # | المصدر | الرابط | ماذا أعطى |
|---|---|---|---|
| 1 | قائمة App Store (SA) عبر iTunes lookup API | https://itunes.apple.com/lookup?id=835599320&country=sa | الوصف الرسمي، 6 لقطات، التصنيف 12+، الحجم 1,080 MB، iOS 15+، الإصدار 47.6.0 بتاريخ 2026-11-02 |
| 2 | Community Guidelines: Overview | https://www.tiktok.com/community-guidelines/en/overview | تصنيف القواعد الكامل (6 أقسام، 23 قاعدة فرعية)، وأنواع الإجراء: إزالة، تقييد عمري، غير مؤهل لـFYF، شاشة اختيارية/لافتة سياق |
| 3 | Community Guidelines: Enforcement | https://www.tiktok.com/community-guidelines/en/enforcement | مراجعة آلية أولى ثم مراجع بشري، مراجعة إضافية عند الانتشار أو البلاغ، الاستئناف عبر Safety Center، حالة البلاغات في المكان نفسه |
| 4 | FYF Standards | https://www.tiktok.com/community-guidelines/en/fyf-standards | المحتوى غير المؤهل للتوصية، والإشعار عبر التحليلات فقط |
| 5 | Newsroom: نظام الإنفاذ المحدّث (2023-02-02) | https://newsroom.tiktok.com/en-us/supporting-creators-with-an-updated-account-enforcement-system | المخالفات تتراكم لكل ميزة ولكل سياسة، تنتهي بعد 90 يومًا، حظر فوري للمخالفات الجسيمة، صفحة Account status وReport records، إشعار قبل الحظر الدائم |
| 6 | Newsroom: كيف يوصي TikTok بالفيديو | https://newsroom.tiktok.com/en-us/how-tiktok-recommends-videos-for-you | إشارات التوصية، اختيار الاهتمامات للمستخدم الجديد، Not interested، تجنب التكرار |
| 7 | Safety: Reporting | https://www.tiktok.com/safety/en/tools-and-guides/reporting | مسار Report records (Profile → Menu → Settings and privacy → Support → Safety Center → Report records)، تحديثات البلاغ في الـInbox «قد» تصل، هوية المبلّغ لا تُكشف |
| 8 | Support: Manage comments | https://support.tiktok.com/en/account-and-privacy/account-privacy-settings/manage-comments | Filter all comments، Filter keywords، Review filtered comments (Approve/Delete)، مسار Settings and privacy → Privacy → Comments |
| 9 | Display API | https://developers.tiktok.com/doc/display-api-get-started | حقول User وVideo العامة |
| 10 | Research API: Query Videos | https://developers.tiktok.com/doc/research-api-specs-query-videos | 23 حقلًا للفيديو (region_code, hashtag_names, video_label, voice_to_text, favorites_count...) |
| 11 | Research API: Query Comments | https://developers.tiktok.com/doc/research-api-specs-query-video-comments | حقول التعليق (parent_comment_id, like_count, reply_count...) |
| 12 | Content Posting API: Direct Post | https://developers.tiktok.com/doc/content-posting-api-reference-direct-post | إعدادات النشر: caption ≤ 2200، privacy_level بأربع قيم، disable_comment/duet/stitch، cover timestamp، brand toggles، is_aigc |
| 13 | Transparency: Community Guidelines Enforcement (Q2 2026) | https://www.tiktok.com/transparency/en/community-guidelines-enforcement/ | 99.5% من المقاطع المخالفة أُزيلت قبل أي بلاغ، 97.4% من الإزالات آلية |
| 14 | Newsroom: تقرير DSA السابع (H1 2026) | https://newsroom.tiktok.com/digital-services-act-our-seventh-transparency-report-on-content-moderation-in-europe | ~104 مليون عنصر أُزيل، 94.1% دون مراجعة بشرية |
| 15 | `replica/fixes.md` و`reviews.csv` | محلي | ما يكرهه المستخدمون: 648 عنصرًا |

**ما لم يُقرأ:** مقالات مركز المساعدة (Report a post / Report a comment / Account status) تُعرض بـJavaScript فقط ولم تُقرأ؛ خطوات البلاغ التفصيلية أدناه مبنية على صفحة Reporting العامة ومعرفة عامة بالتطبيق، مستواها **medium**. حساب المستخدم لم يُستخدم؛ إن أراد التحقق من حالة «فارغ/خطأ» لكل شاشة فليفتح حسابه معي لاحقًا.

## الحلقة الأساسية

المستخدم يفتح التطبيق على خلاصة عمودية لا تنتهي، يسحب لأعلى، يتفاعل (إعجاب/تعليق/مشاركة/حفظ)، وأحيانًا ينشر؛ كل تفاعل يعيد تشكيل الخلاصة. الشيء الذي «يدفع» له المستخدم هنا هو الزمن والانتباه، والمبدع يدفع بالمحتوى مقابل الانتشار.

**ما نعد به ولا يعد به الأصل:** كل إجراء إشراف له سبب مكتوب بالعربية، وكل استئناف يصل إلى إنسان خلال مهلة معلنة (الأصل: 94–97% آلي، والإشعار «قد» يصل).

## الشاشات

| ID | الشاشة | الوصول | الغرض | المكونات الرئيسية | الحالات |
|---|---|---|---|---|---|
| S01 | دخول/تسجيل | أول فتح أو من الملف الشخصي | هاتف/بريد/Apple/Google، تاريخ الميلاد | حقول، OTP، أزرار مزودين | فارغ، خطأ OTP، أقل من 13 (رفض)، 13–17 (حساب قاصر) |
| S02 | اختيار الاهتمامات | بعد التسجيل، يمكن تخطيه | بذر الخلاصة الأولى | شبكة رقائق قابلة للتحديد | لا اختيار (خلاصة عامة)، 1+ |
| S03 | الخلاصة الرئيسية | التبويب الأول | فيديو ملء الشاشة، تبويبات علوية Following / Friends / For You | مشغل، شريط إجراءات يمين (الملف، إعجاب، تعليق، حفظ، مشاركة)، نص التعليق التوضيحي والصوت، شريط تنقل سفلي | تحميل، لا اتصال، Following فارغ، فيديو بشاشة تحذير اختيارية، لافتة سياق، وسم AI، إعلان |
| S04 | ورقة خيارات الفيديو | ضغطة مطوّلة على S03 | Not interested، حفظ، إخفاء مبدع، إخفاء صوت، سرعة، Report | قائمة أيقونات | عادي، فيديو خاص بي (حذف/خصوصية) |
| S05 | ورقة التعليقات | أيقونة التعليق في S03 | قراءة وكتابة التعليقات والردود | قائمة تعليقات، خيط ردود قابل للطي، حقل إدخال مع @ و#، إعجاب، ضغطة مطوّلة (رد/إبلاغ/حذف/تثبيت) | فارغ («كن أول من يعلق»)، التعليقات معطلة، تعليقي قيد التصفية، محذوف بالإشراف |
| S06 | ورقة المشاركة | أيقونة المشاركة | إرسال، نسخ الرابط، Repost، حفظ الفيديو، Report | شبكة وجهات + صف إجراءات | عادي، الحفظ معطل من المالك |
| S07 | البحث | أيقونة أعلى الخلاصة | Top / Videos / Users / Hashtags | حقل بحث، تبويبات، شبكة نتائج | فارغ، لا نتائج، كلمة محجوبة |
| S08 | الكاميرا | زر + في الشريط السفلي | تسجيل 15ث/60ث/3د/10د، رفع من المعرض، مؤقت، سرعة، قلب | عدسة، دائرة تسجيل مقطّعة، شريط أدوات | إذن الكاميرا مرفوض، تسجيل متعدد المقاطع |
| S09 | المحرر | بعد التسجيل/الرفع | قص، نص، ملصقات، فلاتر، تعليق صوتي، ترجمة تلقائية | خط زمني، أدوات، معاينة | معالجة، فشل الترجمة التلقائية |
| S10 | إعدادات النشر | «التالي» من S09 | التعليق التوضيحي ≤ 2200، # و@، غلاف، الخصوصية (الجميع/الأصدقاء/المتابعون/أنا فقط)، السماح بالتعليقات، وسم AI، إفصاح تجاري، حفظ مسودة، نشر | نموذج، مفاتيح، منتقي غلاف | تحقق مسبق من المحتوى (اختياري)، مسودة محفوظة |
| S11 | حالة النشر | بعد «نشر» | رفع → معالجة → قيد المراجعة → منشور / فشل | شريط تقدم فوق الملف الشخصي، شارة | رفع متوقف، فشل مع سبب، «قيد المراجعة» (مشاهدات 0) |
| S12 | الملف الشخصي | التبويب الأخير | شبكة الفيديوهات، مسودات، خاص، إعجابات، الإعدادات والتحليلات | رأس (صورة، اسم، إحصاءات)، تبويبات، شبكة | فارغ، مسودات، فيديو محذوف بالإشراف يظهر للمالك بعلامة |
| S13 | صندوق الإشعارات | التبويب الرابع | نشاط (إعجابات، تعليقات، إشارات، متابعون) + إشعارات النظام (إزالة، مخالفة، تحديث استئناف، تحديث بلاغ) | قائمة خلايا، فلاتر | فارغ، غير مقروء |
| S14 | البلاغ | S04/S05/S06/الملف الشخصي | اختيار السبب → سبب فرعي → تفاصيل اختيارية → إرسال → تأكيد + حظر اختياري | قائمة راديو متعددة المستويات، نص حر، زر | مُرسل، بلاغ مكرر |
| S15 | Safety Center | Settings and privacy → Support → Safety Center | مدخل لـAccount status وReport records | قائمة | — |
| S16 | Account status | S15 | قائمة المخالفات: المحتوى، التاريخ، السياسة، الإجراء، المخالفات النشطة وتاريخ انتهائها (90 يومًا)، زر استئناف | قائمة، شرائح حالة، تحذير «على وشك الحظر» | نظيف، مخالفات نشطة، تحذير حظر |
| S17 | Report records | S15 | بلاغاتي: قيد المراجعة / وُجدت مخالفة / لم توجد | قائمة، شرائح حالة | فارغ، «اطلب مراجعة أخرى» (محدود إقليميًا في الأصل) |
| S18 | إشعار الإزالة والاستئناف | من S13 أو S16 | سبب الإزالة، مقتطف السياسة، «Submit an appeal»، نص، حالة الاستئناف بعد الإرسال | بطاقة قرار، نموذج | أُرسل، مقبول (أُعيد المحتوى والمخالفة أُزيلت)، مرفوض |
| S19 | إعدادات التعليقات | Settings and privacy → Privacy → Comments | من يعلق، Filter all comments، Filter keywords، Review filtered comments (Approve/Delete) | مفاتيح، قائمة كلمات، قائمة مراجعة | لا كلمات، تعليقات مصفّاة بانتظار |
| S20 | تفضيلات المحتوى | Settings and privacy → Content preferences | تحديث خلاصة For You، فلترة كلمات في الخلاصة، إدارة وقت الشاشة | قائمة، إدخال كلمات | — |

## التدفقات

```
F01 مشاهدة وتفاعل
    S03 -> (إعجاب | S05 تعليق | S06 مشاركة/حفظ)
    نقرات المسار السعيد: 0 للمشاهدة، 1 للإعجاب، 3 للتعليق (أيقونة، كتابة، إرسال)
    edge: لا اتصال، فيديو بشاشة تحذير، Following فارغ، إعلان، فيديو موسوم AI

F02 تشكيل الخلاصة
    S03 -> S04 (Not interested | إخفاء مبدع | إخفاء صوت) | S20 (فلترة كلمات، تحديث الخلاصة)
    نقرات: 2
    edge: المستخدم الجديد بلا اهتمامات، تكرار المبدع نفسه

F03 نشر فيديو
    S08 -> S09 -> S10 -> S11 -> S12
    نقرات المسار السعيد: ~8 (+, تسجيل/رفع, التالي, التالي, كتابة التعليق, اختيار الخصوصية, نشر)
    edge: الرفع يتوقف، الفيديو «قيد المراجعة» بلا مشاهدات، رُفض قبل النشر، وسم AI إلزامي، حفظ كمسودة

F04 تعليق ورد، والمالك يدير التعليقات
    S05 -> كتابة -> إرسال ; المالك: S19 -> Review filtered -> Approve/Delete ; S05 ضغطة مطوّلة -> تثبيت/حذف/إبلاغ
    نقرات: 3 للتعليق، 4 لاعتماد تعليق مصفّى
    edge: التعليق محجوز بفلتر الكلمات (المعلّق يراه، غيره لا)، التعليقات معطلة، تعليقي حُذف بالإشراف

F05 إبلاغ عن فيديو/تعليق/حساب
    S06|S04|S05|S12 -> S14 سبب -> سبب فرعي -> تفاصيل -> إرسال -> تأكيد -> (لاحقًا) S13 إشعار + S17 حالة
    نقرات: 5
    edge: بلاغ مكرر على العنصر نفسه، انتحال شخص غير مشهور (الأصل لا يوفره بوضوح)، النتيجة «لم توجد مخالفة» بلا تفسير (الأصل)

F06 استلام إشعار إزالة واستئناف
    S13 -> S18 (السبب + السياسة) -> Submit an appeal -> نص -> إرسال -> S16 حالة -> S13 نتيجة
    نقرات: 4
    edge: الإزالة آلية بلا مراجع، المحتوى FYF-ineligible فقط (يُعرف من التحليلات لا من إشعار)، رفض الاستئناف بلا سبب، مهلة الاستئناف مجهولة (الأصل)

F07 المبدع يتحقق من حالة حسابه
    S12 -> Settings -> Support -> S15 -> S16
    نقرات: 5
    edge: مخالفة ستنتهي بعد N يومًا، تحذير «على وشك الحظر الدائم»

F08 المبلّغ يتابع نتيجة بلاغه
    S12 -> ... -> S15 -> S17 -> البلاغ
    نقرات: 6
    edge: الحالة «قيد المراجعة» لأسابيع، «لم توجد مخالفة» بلا تصعيد (الأصل)
```

العدد الذي يجب التفوق عليه: الوصول إلى حالة البلاغ أو الحساب يحتاج 5–6 نقرات مدفونة في الإعدادات في الأصل؛ المستهدف 2 (أيقونة دائمة في صندوق الإشعارات).

## المكونات

| المكوّن | المتغيرات | الحالات | يُستخدم في |
|---|---|---|---|
| شريط تنقل سفلي | 5 عناصر، زر + مميز | نشط، شارة عدد | كل الشاشات الرئيسية |
| تبويبات علوية | Following / Friends / For You؛ تبويبات البحث والملف | نشط، تحميل | S03, S07, S12 |
| مشغل فيديو عمودي | ملء الشاشة، كتم، تقدم | تحميل، تشغيل، إيقاف، خطأ، شاشة تحذير اختيارية | S03, S12 |
| شريط إجراءات يمين | صورة مبدع + متابعة، إعجاب، تعليق، حفظ، مشاركة | عدّاد، مُفعّل | S03 |
| نص توضيحي + شريط صوت | مطوي/مفتوح، # و@ قابلة للنقر | طويل، مترجم | S03 |
| ورقة سفلية | تعليقات، مشاركة، خيارات، بلاغ | نصف/كامل، فارغة | S04–S06, S14 |
| خلية تعليق | أصل، رد، مثبّت، من المبدع، مصفّى | إعجاب، محذوف، قيد التصفية | S05, S19 |
| حقل إدخال نص | تعليق، تعليق توضيحي، استئناف | عدّاد حروف (2200)، @ و#، إيموجي | S05, S10, S18 |
| قائمة راديو متعددة المستويات | أسباب البلاغ | محدد، سبب فرعي | S14 |
| شريحة حالة | قيد المراجعة، مخالفة، لا مخالفة، أُزيل، أُعيد، ينتهي بعد N يومًا | ألوان دلالية | S11, S16, S17, S18 |
| بطاقة قرار إشراف | السياسة، السبب، الإجراء، زر استئناف | مفتوح، مُستأنف، نهائي | S13, S16, S18 |
| مفتاح/قائمة إعدادات | خصوصية، تعليقات، فلاتر | مفعّل، غير متاح للقاصر | S10, S19, S20 |
| شريط تقدم الرفع | فوق شبكة الملف | رفع، معالجة، فشل مع إعادة | S11, S12 |
| وسوم على الفيديو | AI-generated، شراكة مدفوعة، لافتة سياق، شاشة تحذير | — | S03 |
| toast/alert | «شكرًا لبلاغك»، «حُفظ كمسودة»، تحذير حظر | — | عام |
| رقائق اهتمامات | قابلة للتحديد المتعدد | محدد | S02 |

## نموذج البيانات المستنتج

```
User        id, handle, display_name, avatar_url, bio, birth_date, region_code, language,
            is_private, follower_count, following_count, like_count,
            comment_permission (everyone|friends|none), filter_all_comments (bool),
            keyword_filters (list), is_minor (derived), created_at
            evidence: S01, S12, S19, Display API user, Research API username/region_code
            confidence: high

Video       id, user_id, caption (<=2200), hashtags (list), mentions (list),
            duration_s, cover_url, cover_timestamp_ms, media_url (HLS), status
            (uploading|processing|under_review|published|removed|failed),
            privacy_level (PUBLIC_TO_EVERYONE|MUTUAL_FOLLOW_FRIENDS|FOLLOWER_OF_CREATOR|SELF_ONLY),
            allow_comments, allow_duet, allow_stitch, is_aigc, brand_content, brand_organic,
            view_count, like_count, comment_count, share_count, favorites_count,
            fyf_eligible (bool), age_restricted (bool), warning_screen (bool), context_label,
            voice_to_text, created_at
            evidence: S10 fields = Content Posting API fields، Research API counters/labels
            confidence: high

Draft       id, user_id, clips, caption, settings, saved_at
            evidence: S10 «حفظ مسودة»، S12 تبويب المسودات
            confidence: medium

Comment     id, video_id, user_id, parent_comment_id (nullable), text, like_count, reply_count,
            status (visible|filtered_pending|approved|deleted_by_owner|removed_by_moderation),
            is_pinned, created_at
            evidence: Research API comment object، S05، S19
            confidence: high

Like / Favorite / Follow / Repost   (user_id, target_id, created_at) — جداول ربط
            evidence: S03 شريط الإجراءات، عدّادات الـAPI
            confidence: high

Hashtag     name, video_count ; VideoHashtag (video_id, hashtag) 
            evidence: hashtag_names في Research API، S07
            confidence: high

FeedPreference  user_id, not_interested_video_ids, hidden_user_ids, hidden_sound_ids,
            keyword_filters, interests (list), last_refresh_at
            evidence: S04, S20, مصدر 6
            confidence: medium

FeedEvent   user_id, video_id, watch_ms, completed, liked, shared, commented, skipped, ts
            evidence: مصدر 6 (إشارات التوصية: الإكمال أقوى إشارة)
            confidence: medium (الحقول مستنتجة من الوصف لا من واجهة)

Report      id, reporter_id, target_type (video|comment|user), target_id,
            reason_code (من تصنيف القواعد: 23 قاعدة فرعية)، sub_reason, details,
            status (under_review|violation_found|no_violation), outcome_explanation (نضيفه)،
            escalation_requested (نضيفه)، created_at, resolved_at
            evidence: S14, S17, مصدر 7، مصدر 2 للتصنيف
            confidence: high للبنية، medium لقيم الحالة

ModerationDecision  id, target_type, target_id, policy_code, action
            (removed|fyf_ineligible|age_restricted|warning_screen|context_label|account_ban|
             feature_restriction), decided_by (auto|human), reason_ar, reason_en,
            evidence_segment (start_ms, end_ms | comment_id) (نضيفه)، created_at
            evidence: مصدر 2 و3 (أنواع الإجراء)، مصدر 13 (آلي/بشري)
            confidence: high للأنواع، guess لحقل المقطع

Strike      id, user_id, decision_id, feature (post|comment|profile), policy_code,
            issued_at, expires_at (= issued_at + 90d), active
            evidence: مصدر 5 (لكل ميزة ولكل سياسة، 90 يومًا، عتبات غير معلنة)
            confidence: high للمدة، guess للعتبات

Appeal      id, decision_id, user_id, text, status (submitted|in_review|accepted|rejected),
            reviewer_id (human) (نضيفه)، sla_due_at (نضيفه)، decided_at, decision_reason_ar
            evidence: S18, مصدر 3 و5
            confidence: medium

Notification  id, user_id, type (like|comment|mention|follow|removal|strike|appeal_update|
            report_update|ban_warning), ref_type, ref_id, read, created_at
            evidence: S13, مصدر 5 و7
            confidence: high
```

العلاقات: User 1-n Video، Video 1-n Comment (Comment self-ref عبر parent_comment_id)، User n-n Video عبر Like/Favorite/Repost، User n-n User عبر Follow، Report n-1 (Video|Comment|User)، ModerationDecision 1-n Strike، ModerationDecision 1-1 Appeal (كحد أقصى واحد نشط)، User 1-n Notification.

ما لا نعرفه ونضع له افتراضًا: عتبات المخالفات (نقترح: 3 نشطة في الميزة نفسها = تقييد مؤقت، 5 تراكمية = مراجعة بشرية إلزامية قبل أي حظر)، مهلة الاستئناف (نقترح 30 يومًا للتقديم، 48 ساعة للرد البشري).

## مصفوفة الميزات

انظر `features.csv`: 79 صفًا. must 40، should 20، could 10، skip 9، منها 18 صف إصلاح من `fixes.md` بـ`original=no`.

## خارج النطاق (لا يمكن أو لا ينبغي استنساخه)

- **مكتبة الموسيقى والأصوات المرخصة.** الأصل يملك تراخيص مع شركات التسجيل. البديل: صوت المستخدم الأصلي فقط + مكتبة مرخّصة بلا حقوق لاحقًا.
- **مكتبة المؤثرات وفلاتر AR.** أصول خاصة. البديل: فلاتر لونية أساسية + نص وملصقات.
- **الشبكة والمستخدمون والمحتوى القائم.** لا يُستنسخ؛ مشكلة الانطلاقة الباردة محلولة بالمنتج والتوزيع لا بالكود.
- **خوارزمية التوصية بحجمها.** نبدأ ببسيط: اهتمامات + شعبية + حداثة + إشارات الإكمال، مع تجنب تكرار المبدع والصوت (مصدر 6).
- **LIVE، الهدايا، العملات، المتجر، Creator Rewards.** مدفوعات ومراقبة فورية وتراخيص؛ خارج الشريحة بقرار.
- **Duet/Stitch.** يحتاج محتوى مشتقًا من مكتبة قائمة؛ مؤجل.
- **الرسائل الخاصة.** خارج الشريحة؛ سطح إساءة كبير يحتاج إشرافًا خاصًا.
- **الإبلاغ للجهات القانونية (NCMEC وما يماثله).** التزام قانوني يُحل بمزود متخصص لا بكود مبدئي.
- **البيانات الديموغرافية والتحليلات المتقدمة للمبدعين.** لاحقًا.

## الحجم

الشاشات 20، التدفقات 8، الكيانات 14. الأجزاء الصعبة: (1) خط أنابيب الفيديو (رفع مقسّم، تحويل، HLS، CDN)، (2) خط الإشراف: فحص آلي أول ثم طابور بشري بمهلة معلنة وسجل مخالفات متسق مع انتهاء 90 يومًا، (3) شرح القرار بالعربية مع تحديد المقطع المخالف، (4) الانطلاقة الباردة للخلاصة، (5) التحقق من العمر دون طريق مسدود. **الحجم: L (ربع سنة) لفريق صغير، مع قبول أن التوصية في النسخة الأولى بسيطة.** ليس هناك وعد بنسخة «مثالية»؛ `replica-diff` سيعطي الرقم.
