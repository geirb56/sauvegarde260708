import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

export default function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    const { error } = await signIn(email, password);
    setLoading(false);
    if (error) {
      toast.error(error.message || "Login failed. Please check your credentials.");
    } else {
      navigate("/");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: "var(--bg-primary)" }}>
      <Card className="w-full max-w-sm">
        <CardContent className="p-6 space-y-5">
          <div className="flex flex-col items-center space-y-2">
            <img src="/runindex-logo.png" alt="RunIndex" className="h-10 w-auto" />
            <h1 className="text-xl font-bold">Sign in to RunIndex</h1>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="you@example.com"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
              Sign in
            </Button>
          </form>

          <p className="text-sm text-center text-muted-foreground">
            No account yet?{" "}
            <Link to="/signup" className="text-primary underline">
              Create one for free
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
