import java.nio.file.*;
import jdk.internal.org.objectweb.asm.*;

/** Offline build-time patcher for exact approved Preview 10.0.42; never ship in the JAR. */
public final class WeaveHypeClient {
    public static void main(String[] args) throws Exception {
        byte[] input = Files.readAllBytes(Path.of(args[0]));
        ClassReader reader = new ClassReader(input);
        ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
        final int[] markers = {0, 0};
        reader.accept(new ClassVisitor(Opcodes.ASM8, writer) {
            @Override public MethodVisitor visitMethod(int access, String name, String desc,
                                                          String signature, String[] exceptions) {
                MethodVisitor mv = super.visitMethod(access, name, desc, signature, exceptions);
                if ("lambda$login$1".equals(name) &&
                        "(JLcom/google/gson/JsonObject;)Lcom/google/gson/JsonObject;".equals(desc)) {
                    return new MethodVisitor(Opcodes.ASM8, mv) {
                        @Override public void visitInsn(int opcode) {
                            if (opcode == Opcodes.ARETURN) {
                                super.visitVarInsn(Opcodes.ALOAD, 4);
                                super.visitMethodInsn(Opcodes.INVOKESTATIC,
                                        "br/clanhype/client/HypeAutoStagingBridge",
                                        "afterLogin", "(Ljava/lang/String;)V", false);
                                markers[0]++;
                            }
                            super.visitInsn(opcode);
                        }
                    };
                }
                if ("logout".equals(name) && "()V".equals(desc)) {
                    return new MethodVisitor(Opcodes.ASM8, mv) {
                        @Override public void visitCode() {
                            super.visitCode();
                            super.visitMethodInsn(Opcodes.INVOKESTATIC,
                                    "br/clanhype/client/HypeAutoStagingBridge",
                                    "afterLogout", "()V", false);
                            markers[1]++;
                        }
                    };
                }
                return mv;
            }
        }, 0);
        if (markers[0] != 1 || markers[1] != 1)
            throw new IllegalStateException("Unexpected HypeBreedApi bytecode; refusing patch: " +
                                            markers[0] + "," + markers[1]);
        Files.write(Path.of(args[1]), writer.toByteArray());
        System.out.println("Weave HypeBreedApi successful: login=" + markers[0] +
                " logout=" + markers[1]);
    }
}
