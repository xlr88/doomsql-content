# doomsql-content

SQL practice questions for the DoomSQL Android app. They're served to the app through jsDelivr:

https://cdn.jsdelivr.net/gh/xlr88/doomsql-content@main/questions/manifest.json

**To add, edit or publish questions, see [gen_sql_ques.md](gen_sql_ques.md).**

Quick version:

```bash
# AI: generate, check and publish 5 easy, 6 medium, 2 hard questions
python3 ai_gen.py auto --e 5 --m 6 --h 2
```

By hand:

```bash
python3 generate_sql_ques/add_question.py --file drafts/my_question.json
python3 generate_sql_ques/validate_questions.py
git add questions/ && git commit -m "Add question" && git push origin main
```

This repo must stay **public**, because jsDelivr can't read private repos. It holds only
question JSON and the Python tools. The app code lives in a separate private repo.
