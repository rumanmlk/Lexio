import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

// Only a `next dev` build offers the test login; a production build has no such provider.
export const DEV_LOGIN = process.env.NODE_ENV === "development";
const DEV_USER = "dev:local";

declare module "next-auth" {
  interface Session {
    /** The API user id: `google:<sub>`. */
    uid?: string;
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    uid?: string;
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  // One real provider, so one person cannot end up with two accounts. It reads AUTH_GOOGLE_ID and
  // AUTH_GOOGLE_SECRET.
  providers: [
    Google,
    ...(DEV_LOGIN
      ? [Credentials({ id: "dev", name: "Dev login", credentials: {}, authorize: () => ({ id: DEV_USER }) })]
      : []),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    // The session cookie keeps the user id and nothing else: no email, name or picture.
    jwt({ token, account, profile }) {
      if (account?.provider === "google" && profile?.sub) return { uid: `google:${profile.sub}` };
      if (account?.provider === "dev") return { uid: DEV_USER };
      return { uid: token.uid };
    },
    session({ session, token }) {
      return { expires: session.expires, uid: token.uid };
    },
  },
});
