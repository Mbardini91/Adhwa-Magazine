// Adwaa likes — one document per reader per topic: issues/{issueId}/topics/{topicId}/likes/{uid}
import { initializeApp } from 'firebase/app';
import { getAuth, signInAnonymously } from 'firebase/auth';
import { getFirestore, doc, setDoc, deleteDoc, getDoc, collection, getCount, serverTimestamp } from 'firebase/firestore/lite';

window.AdwaaLikes = {
  async connect(cfg, issueId) {
    const app = initializeApp(cfg);
    const auth = getAuth(app);
    await auth.authStateReady();
    if (!auth.currentUser) await signInAnonymously(auth);
    const uid = auth.currentUser.uid;
    const db = getFirestore(app);
    return {
      async get(id) {
        const col = collection(db, 'issues', issueId, 'topics', id, 'likes');
        const [cnt, mine] = await Promise.all([getCount(col), getDoc(doc(col, uid))]);
        return { count: cnt.data().count, liked: mine.exists() };
      },
      async set(id, liked) {
        const ref = doc(db, 'issues', issueId, 'topics', id, 'likes', uid);
        if (liked) await setDoc(ref, { at: serverTimestamp() });
        else await deleteDoc(ref);
      }
    };
  }
};
